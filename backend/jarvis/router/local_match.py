"""Stage A: local routing with zero LLM calls."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from rapidfuzz import fuzz

from ..registry.db import Database, Workflow

HIT_SCORE = 90
CONFIRM_SCORE = 75
SUBSET_GUARD_SCORE = 60

_REPEAT_LAST = re.compile(r"^(repeat|redo|run|do)( the)? (last|previous) (workflow|task|command|one)( again)?$|^do (that|it) again$|^again$")
_REPEAT_DAY = re.compile(r"^(repeat|redo|do) what (we|i) did (yesterday|today)( again)?$")


@dataclass
class LocalMatch:
    kind: str  # hit | confirm | choose | miss
    workflow: Workflow | None = None
    params: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    via: str = ""  # history | pattern | alias | fuzzy
    options: list[dict[str, Any]] = field(default_factory=list)


def _history(db: Database, text: str) -> LocalMatch | None:
    day: str | None = None
    if _REPEAT_LAST.match(text):
        pass
    elif m := _REPEAT_DAY.match(text):
        d = date.today() - timedelta(days=1 if m.group(3) == "yesterday" else 0)
        day = d.isoformat()
    else:
        return None
    runs = db.find_workflow_runs(day)
    if not runs:
        return LocalMatch(kind="miss", via="history")
    if day is not None:
        # several distinct workflows that day -> ask which one
        distinct: dict[tuple, dict] = {}
        for r in runs:
            distinct.setdefault((r["workflow_id"], str(sorted(r["params"].items()))), r)
        if len(distinct) > 1:
            opts = []
            for r in distinct.values():
                wf = db.get_workflow(r["workflow_id"])
                opts.append({"workflow": wf.name if wf else "?", "params": r["params"], "command": r["command_text"],
                             "execution_id": r["id"]})
            return LocalMatch(kind="choose", via="history", options=opts)
    r = runs[0]
    wf = db.get_workflow(r["workflow_id"])
    if wf is None:
        return LocalMatch(kind="miss", via="history")
    if not wf.enabled:  # older version: run the current one
        wf = db.get_workflow_by_name(wf.name) or wf
    return LocalMatch(kind="hit", workflow=wf, params=dict(r["params"]), score=100, via="history")


def match(db: Database, text: str, raw: str | None = None) -> LocalMatch:
    """`text` must already be normalized. `raw` (filler-stripped, original case) is used for slot values."""
    h = _history(db, text)
    if h is not None:
        return h

    workflows = db.list_workflows()
    for wf in workflows:
        for rx in wf.patterns:
            m = re.match(rx, raw, re.I) if raw else None
            m = m or re.match(rx, text)
            if m:
                params = {k: v.strip() for k, v in m.groupdict().items() if v}
                return LocalMatch(kind="hit", workflow=wf, params=params, score=100, via="pattern")

    for wf in workflows:
        if text in wf.aliases:
            return LocalMatch(kind="hit", workflow=wf, score=100, via="alias")

    best: tuple[float, Workflow | None, float] = (0.0, None, 0.0)
    for wf in workflows:
        for a in wf.aliases:
            s = fuzz.token_set_ratio(text, a)
            if s > best[0]:
                best = (s, wf, fuzz.token_sort_ratio(text, a))
    score, wf, whole = best
    # token_set_ratio scores 100 when an alias is a subset of the command ("open notepad" in
    # "open notepad and type hello"); if the command has many extra words, ask instead of running.
    if wf and score >= HIT_SCORE and whole >= SUBSET_GUARD_SCORE:
        return LocalMatch(kind="hit", workflow=wf, score=score, via="fuzzy")
    if wf and score >= CONFIRM_SCORE:
        return LocalMatch(kind="confirm", workflow=wf, score=score, via="fuzzy")
    return LocalMatch(kind="miss", score=score)
