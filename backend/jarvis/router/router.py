"""Router: Stage A (local, free) then Stage B (LLM planner) on a miss."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..registry.db import Database, Workflow
from . import local_match, slots
from .llm_planner import LLMPlanner, Plan, PlanError
from .normalize import normalize, strip_fillers

QUESTIONS = {
    "slug": "Which LeetCode problem? Give me its slug, e.g. two-sum.",
    "query": "What should I search for?",
    "title": "What should the page be titled?",
    "notes": "What are the notes? I won't make them up.",
}


@dataclass
class RouteDecision:
    kind: str  # run | confirm | needs_input | choose | no_plan | error
    route: str = "local"  # local | llm
    workflow: Workflow | None = None
    params: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    plan: Plan | None = None
    message: str = ""
    missing: list[str] = field(default_factory=list)
    options: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0
    via: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "route": self.route,
            "workflow": self.workflow.name if self.workflow else None,
            "params": self.params, "steps": self.steps, "message": self.message, "missing": self.missing,
            "options": self.options, "score": self.score, "via": self.via,
            "reason": self.plan.reason if self.plan else None,
        }


class Router:
    def __init__(self, db: Database, planner: LLMPlanner):
        self.db = db
        self.planner = planner

    def resolve_workflow(self, wf: Workflow, params: dict[str, Any], via: str = "direct",
                         score: float = 100) -> RouteDecision:
        """Fill a workflow's params; ask (never call the LLM) for anything missing."""
        params = slots.coerce_params(wf.params_schema, params)
        missing = slots.missing_params(wf.params_schema, params)
        if missing:
            return RouteDecision(kind="needs_input", workflow=wf, params=params, missing=missing, via=via,
                                 message=QUESTIONS.get(missing[0], f"Please provide {missing[0]}."), score=score)
        errs = slots.validate_params(wf.params_schema, params)
        if errs:
            return RouteDecision(kind="error", workflow=wf, params=params, via=via,
                                 message="Invalid parameters: " + "; ".join(errs))
        return RouteDecision(kind="run", workflow=wf, params=params, steps=slots.build_steps(wf.steps, params),
                             via=via, score=score)

    def route_local(self, text: str) -> RouteDecision | None:
        norm = normalize(text)
        m = local_match.match(self.db, norm, strip_fillers(text))
        if m.kind == "hit" and m.workflow:
            return self.resolve_workflow(m.workflow, m.params, m.via, m.score)
        if m.kind == "confirm" and m.workflow:
            return RouteDecision(kind="confirm", workflow=m.workflow, score=m.score, via=m.via,
                                 message=f"Did you mean '{m.workflow.name}'? (match {m.score:.0f}%)")
        if m.kind == "choose":
            return RouteDecision(kind="choose", options=m.options, via=m.via,
                                 message="Several workflows ran then. Which one should I repeat?")
        if m.via == "history":
            return RouteDecision(kind="error", via="history", message="I found no successful workflow run to repeat.")
        return None

    async def route(self, text: str, execution_id: str | None = None) -> RouteDecision:
        local = self.route_local(text)
        if local is not None:
            return local
        try:
            plan = await self.planner.plan(text, execution_id)
        except PlanError as e:
            return RouteDecision(kind="error", route="llm", message=str(e))
        if plan.needs_input:
            return RouteDecision(kind="needs_input", route="llm", plan=plan, message=plan.needs_input)
        if not plan.steps:
            return RouteDecision(kind="no_plan", route="llm", plan=plan,
                                 message=plan.reason or "I can't do that with the tools I have.")
        return RouteDecision(kind="run", route="llm", plan=plan,
                             steps=[{"tool": s.tool, "args": s.args} for s in plan.steps])


def parameterize(command: str, steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Turn concrete values that appear verbatim in the command into params.

    Returns (steps with args_template, params_schema, regex patterns).
    """
    norm = normalize(command)
    params: dict[str, str] = {}
    templated = []
    for s in steps:
        tmpl = {}
        for k, v in s.get("args", {}).items():
            if isinstance(v, str) and len(v) >= 2 and normalize(v) and normalize(v) in norm:
                name = k if k not in params or params[k] == normalize(v) else f"{k}_{len(params)}"
                params[name] = normalize(v)
                tmpl[k] = "{" + name + "}"
            else:
                tmpl[k] = v
        templated.append({"tool": s["tool"], "args_template": tmpl})
    schema = {"type": "object", "properties": {p: {"type": "string"} for p in params}, "required": list(params)}
    patterns = []
    if params:
        rx = re.escape(norm)
        ok = True
        for name, val in sorted(params.items(), key=lambda kv: -len(kv[1])):
            esc = re.escape(val)
            if esc not in rx:
                ok = False
                break
            rx = rx.replace(esc, f"(?P<{name}>.+)", 1)
        if ok:
            patterns.append(f"^{rx}$")
    return templated, schema, patterns
