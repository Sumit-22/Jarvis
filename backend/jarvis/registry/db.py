"""SQLite repository for workflows, executions and usage."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Workflow:
    id: int
    name: str
    canonical_intent: str
    version: int
    params_schema: dict[str, Any]
    steps: list[dict[str, Any]]
    uses_llm_per_run: bool
    enabled: bool
    last_used_at: str | None = None
    aliases: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "canonical_intent": self.canonical_intent,
            "version": self.version,
            "params_schema": self.params_schema,
            "steps": self.steps,
            "uses_llm_per_run": self.uses_llm_per_run,
            "enabled": self.enabled,
            "last_used_at": self.last_used_at,
            "aliases": self.aliases,
        }


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        self.migrate()

    # -- infrastructure -------------------------------------------------
    def migrate(self) -> None:
        sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(sql)
            row = self._conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                self._conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
            self._conn.commit()

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur.lastrowid or 0

    # -- workflows ------------------------------------------------------
    def _row_to_workflow(self, r: sqlite3.Row) -> Workflow:
        wid = r["id"]
        return Workflow(
            id=wid,
            name=r["name"],
            canonical_intent=r["canonical_intent"],
            version=r["version"],
            params_schema=json.loads(r["params_schema"]),
            steps=json.loads(r["steps"]),
            uses_llm_per_run=bool(r["uses_llm_per_run"]),
            enabled=bool(r["enabled"]),
            last_used_at=r["last_used_at"],
            aliases=[a["alias"] for a in self._q("SELECT alias FROM workflow_aliases WHERE workflow_id=?", (wid,))],
            patterns=[p["regex"] for p in self._q("SELECT regex FROM workflow_patterns WHERE workflow_id=?", (wid,))],
        )

    def list_workflows(self, enabled_only: bool = True) -> list[Workflow]:
        sql = "SELECT * FROM workflows"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY name"
        return [self._row_to_workflow(r) for r in self._q(sql)]

    def get_workflow(self, workflow_id: int) -> Workflow | None:
        rows = self._q("SELECT * FROM workflows WHERE id=?", (workflow_id,))
        return self._row_to_workflow(rows[0]) if rows else None

    def get_workflow_by_name(self, name: str) -> Workflow | None:
        rows = self._q("SELECT * FROM workflows WHERE name=? AND enabled=1 ORDER BY version DESC LIMIT 1", (name,))
        return self._row_to_workflow(rows[0]) if rows else None

    def save_workflow(
        self,
        name: str,
        steps: list[dict[str, Any]],
        params_schema: dict[str, Any],
        aliases: list[str],
        patterns: list[str] | None = None,
        canonical_intent: str = "",
        uses_llm_per_run: bool = False,
        replace_patterns: bool = False,
    ) -> Workflow:
        """Insert a workflow. If the name exists, bump version and disable the old row (kept for history).

        Aliases of the old version are kept; its patterns too unless replace_patterns (used by seed updates).
        """
        with self._lock:
            prev = self.get_workflow_by_name(name)
            version = 1
            if prev:
                version = prev.version + 1
                self._x("UPDATE workflows SET enabled=0 WHERE id=?", (prev.id,))
                aliases = list(dict.fromkeys(prev.aliases + aliases))
                if not replace_patterns:
                    patterns = list(dict.fromkeys(prev.patterns + (patterns or [])))
            wid = self._x(
                "INSERT INTO workflows (name, canonical_intent, version, params_schema, steps, uses_llm_per_run, created_at, enabled)"
                " VALUES (?,?,?,?,?,?,?,1)",
                (name, canonical_intent, version, json.dumps(params_schema), json.dumps(steps), int(uses_llm_per_run), now_iso()),
            )
            for a in dict.fromkeys(aliases):
                self._x("INSERT INTO workflow_aliases (workflow_id, alias) VALUES (?,?)", (wid, a))
            for p in patterns or []:
                self._x("INSERT INTO workflow_patterns (workflow_id, regex) VALUES (?,?)", (wid, p))
        wf = self.get_workflow(wid)
        assert wf is not None
        return wf

    def touch_workflow(self, workflow_id: int) -> None:
        self._x("UPDATE workflows SET last_used_at=? WHERE id=?", (now_iso(), workflow_id))

    # -- executions -----------------------------------------------------
    def create_execution(self, command_text: str, route: str, workflow_id: int | None = None,
                         params: dict | None = None, plan: list | None = None) -> str:
        eid = uuid.uuid4().hex[:12]
        self._x(
            "INSERT INTO executions (id, workflow_id, command_text, route, status, params, plan, started_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (eid, workflow_id, command_text, route, "running", json.dumps(params or {}),
             json.dumps(plan) if plan is not None else None, now_iso()),
        )
        return eid

    def set_execution_plan(self, eid: str, plan: list) -> None:
        self._x("UPDATE executions SET plan=? WHERE id=?", (json.dumps(plan), eid))

    def finish_execution(self, eid: str, status: str, error: str | None = None) -> None:
        self._x("UPDATE executions SET status=?, ended_at=?, error=? WHERE id=?", (status, now_iso(), error, eid))

    def get_execution(self, eid: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM executions WHERE id=?", (eid,))
        if not rows:
            return None
        d = dict(rows[0])
        d["params"] = json.loads(d["params"] or "{}")
        d["plan"] = json.loads(d["plan"]) if d["plan"] else None
        d["steps"] = [dict(s) for s in self._q("SELECT * FROM execution_steps WHERE execution_id=? ORDER BY idx", (eid,))]
        return d

    def recent_executions(self, limit: int = 30) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT * FROM executions ORDER BY started_at DESC LIMIT ?", (limit,))]

    def find_workflow_runs(self, date_prefix: str | None = None) -> list[dict[str, Any]]:
        """Succeeded executions that ran a workflow, newest first. date_prefix is a local YYYY-MM-DD."""
        rows = self._q(
            "SELECT * FROM executions WHERE workflow_id IS NOT NULL AND status='succeeded' ORDER BY started_at DESC LIMIT 200"
        )
        out = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d["params"] or "{}")
            if date_prefix:
                local = datetime.fromisoformat(d["started_at"]).astimezone().strftime("%Y-%m-%d")
                if local != date_prefix:
                    continue
            out.append(d)
        return out

    def add_step(self, eid: str, idx: int, tool: str, args: dict) -> int:
        return self._x(
            "INSERT INTO execution_steps (execution_id, idx, tool, args, status) VALUES (?,?,?,?,?)",
            (eid, idx, tool, json.dumps(args, default=str), "running"),
        )

    def finish_step(self, step_id: int, status: str, attempts: int, result: Any, verification: Any) -> None:
        self._x(
            "UPDATE execution_steps SET status=?, attempts=?, result=?, verification=? WHERE id=?",
            (status, attempts, json.dumps(result, default=str), json.dumps(verification, default=str), step_id),
        )

    # -- usage ----------------------------------------------------------
    def record_usage(self, execution_id: str | None, purpose: str, provider: str, model: str,
                     input_tokens: int | None, output_tokens: int | None, est_cost: float | None) -> None:
        self._x(
            "INSERT INTO llm_usage (execution_id, purpose, provider, model, input_tokens, output_tokens, est_cost, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (execution_id, purpose, provider, model, input_tokens, output_tokens, est_cost, now_iso()),
        )

    def usage_summary(self) -> dict[str, Any]:
        by_purpose = {}
        for r in self._q(
            "SELECT purpose, COUNT(*) calls, SUM(input_tokens) inp, SUM(output_tokens) outp, SUM(est_cost) cost,"
            " SUM(CASE WHEN est_cost IS NULL THEN 1 ELSE 0 END) unknown_cost FROM llm_usage GROUP BY purpose"
        ):
            by_purpose[r["purpose"]] = {
                "calls": r["calls"],
                "input_tokens": r["inp"] or 0,
                "output_tokens": r["outp"] or 0,
                "est_cost": r["cost"],
                "calls_with_unknown_cost": r["unknown_cost"],
            }
        hits = self._q("SELECT COUNT(*) c FROM executions WHERE route='local'")[0]["c"]
        misses = self._q("SELECT COUNT(*) c FROM executions WHERE route='llm'")[0]["c"]
        planner = by_purpose.get("planner", {}).get("calls", 0)
        return {"planner_calls": planner, "cache_hits": hits, "cache_misses": misses, "by_purpose": by_purpose}

    def usage_for_execution(self, eid: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT * FROM llm_usage WHERE execution_id=?", (eid,))]
