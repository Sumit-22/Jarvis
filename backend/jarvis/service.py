"""Orchestrates a command: route -> record execution -> execute -> offer to save. Shared by API and tests."""
from __future__ import annotations

import asyncio
from typing import Any

from . import logging as jlog
from .config import Settings
from .executor.approvals import ApprovalManager
from .executor.cancel import CancelRegistry
from .executor.events import EventBus
from .executor.runner import Executor, RunOutcome
from .registry.db import Database, Workflow
from .router.router import RouteDecision, Router, parameterize
from .tools.base import ToolRegistry


class Jarvis:
    def __init__(self, settings: Settings, db: Database, registry: ToolRegistry, router: Router,
                 bus: EventBus | None = None, approvals: ApprovalManager | None = None):
        self.settings = settings
        self.db = db
        self.registry = registry
        self.router = router
        self.bus = bus or EventBus()
        self.approvals = approvals or ApprovalManager()
        self.cancels = CancelRegistry()
        self.executor = Executor(registry, db, self.bus, self.approvals, max_retries=settings.max_retries,
                                 approval_timeout_s=settings.approval_timeout_s, dry_run=settings.dry_run,
                                 step_timeout_s=settings.step_timeout_s)
        self._lock = asyncio.Lock()  # one desktop-touching run at a time

    def _uses_llm(self, steps: list[dict[str, Any]]) -> bool:
        return any(s["tool"] in self.registry and self.registry.get(s["tool"]).uses_llm for s in steps)

    async def handle_command(self, text: str) -> dict[str, Any]:
        self.bus.emit("command", text=text)
        self.bus.set_state("planning")
        local = self.router.route_local(text)
        if local is not None:
            return await self._act(text, local)
        # LLM route: create the execution first so planner usage is attributed to it.
        eid = self.db.create_execution(text, "llm")
        decision = await self.router.route(text, eid)
        return await self._act(text, decision, execution_id=eid)

    async def run_workflow(self, name: str, params: dict[str, Any], command_text: str | None = None) -> dict[str, Any]:
        wf = self.db.get_workflow_by_name(name)
        if wf is None:
            return {"kind": "error", "message": f"No workflow named {name!r}"}
        decision = self.router.resolve_workflow(wf, params)
        return await self._act(command_text or f"run workflow {name}", decision)

    async def _act(self, text: str, d: RouteDecision, execution_id: str | None = None) -> dict[str, Any]:
        resp = d.to_dict()
        if d.kind != "run":
            if execution_id:
                status = "needs_input" if d.kind == "needs_input" else "failed"
                self.db.finish_execution(execution_id, status, d.message if status == "failed" else None)
            self.bus.set_state("error" if d.kind == "error" else "idle")
            self.bus.emit("route", **resp)
            return resp

        wf: Workflow | None = d.workflow
        if execution_id is None:
            execution_id = self.db.create_execution(text, d.route, wf.id if wf else None, d.params, d.steps)
        else:
            self.db.set_execution_plan(execution_id, d.steps)
        if wf:
            self.db.touch_workflow(wf.id)
        resp["execution_id"] = execution_id
        resp["uses_llm_per_run"] = self._uses_llm(d.steps)
        self.bus.emit("route", execution_id=execution_id, **{k: v for k, v in resp.items() if k != "execution_id"})
        jlog.log("routed", execution_id, route=d.route, via=d.via, workflow=resp["workflow"], steps=d.steps)

        cancel = self.cancels.create(execution_id)
        try:
            async with self._lock:
                outcome: RunOutcome = await self.executor.run(execution_id, d.steps, cancel)
        finally:
            self.cancels.remove(execution_id)
        resp["status"] = outcome.status
        resp["error"] = outcome.error
        resp["say"] = outcome.say
        resp["steps_result"] = [s.__dict__ for s in outcome.steps]
        if d.route == "llm" and outcome.all_verified and not self.settings.dry_run:
            suggested = self._suggest_name(d)
            resp["offer_save"] = {"execution_id": execution_id, "suggested_name": suggested,
                                  "message": f"Save this as a workflow? Suggested name: {suggested}"}
            self.bus.emit("offer_save", **resp["offer_save"])
        await self._speak_result(outcome)
        return resp

    def _suggest_name(self, d: RouteDecision) -> str:
        tools = [s["tool"] for s in d.steps]
        base = "_".join(dict.fromkeys(t.split("_")[0] for t in tools))[:40] or "workflow"
        name, n = base + "_flow", 2
        while self.db.get_workflow_by_name(name):
            name, n = f"{base}_flow_{n}", n + 1
        return name

    def save_from_execution(self, execution_id: str, name: str) -> Workflow:
        ex = self.db.get_execution(execution_id)
        if ex is None or ex["route"] != "llm" or ex["status"] != "succeeded" or not ex["plan"]:
            raise ValueError("Only a succeeded, fully verified LLM-planned run can be saved.")
        if any(not s["verification"] or '"passed": true' not in s["verification"] for s in ex["steps"]):
            raise ValueError("Every step must have passed verification before saving.")
        steps, schema, patterns = parameterize(ex["command_text"], ex["plan"])
        from .router.normalize import normalize
        wf = self.db.save_workflow(name=name, steps=steps, params_schema=schema, aliases=[normalize(ex["command_text"])],
                                   patterns=patterns, canonical_intent=ex["command_text"],
                                   uses_llm_per_run=self._uses_llm(ex["plan"]))
        self.bus.emit("workflow_saved", workflow=wf.to_dict())
        jlog.log("workflow_saved", execution_id, name=name, version=wf.version)
        return wf

    def stop(self, execution_id: str | None = None) -> int:
        if execution_id:
            return int(self.cancels.cancel(execution_id))
        return self.cancels.cancel_all()

    async def _speak_result(self, outcome: RunOutcome) -> None:
        tts = getattr(self, "tts", None)
        if tts is None or not self.settings.tts_enabled or self.settings.dry_run:
            return
        msg = (outcome.say or "Done.") if outcome.status == "succeeded" else f"Run {outcome.status}."
        try:
            await tts.speak(msg)
        except Exception as e:  # TTS must never break a run
            jlog.log("tts_failed", outcome.execution_id, error=str(e))
