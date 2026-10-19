"""Executor: validates and runs plan steps with timeout, bounded retries, verification, approvals, cancel, dry-run."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .. import logging as jlog
from ..registry.db import Database
from ..tools.base import ToolRegistry, ToolRegistryError, ToolResult, VerificationResult
from .approvals import ApprovalManager
from .cancel import CancelToken
from .events import EventBus


class _Cancelled(Exception):
    pass


@dataclass
class StepOutcome:
    tool: str
    status: str  # succeeded | failed | cancelled | skipped_dry_run
    attempts: int = 0
    result: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class RunOutcome:
    execution_id: str
    status: str  # succeeded | failed | cancelled
    steps: list[StepOutcome] = field(default_factory=list)
    error: str | None = None

    @property
    def all_verified(self) -> bool:
        return self.status == "succeeded" and all(
            s.verification and s.verification.get("passed") for s in self.steps
        )


class Executor:
    def __init__(self, registry: ToolRegistry, db: Database, bus: EventBus, approvals: ApprovalManager,
                 *, max_retries: int = 2, approval_timeout_s: float = 120.0, dry_run: bool = False,
                 step_timeout_s: float | None = None):
        self.registry = registry
        self.db = db
        self.bus = bus
        self.approvals = approvals
        self.max_retries = max_retries
        self.approval_timeout_s = approval_timeout_s
        self.dry_run = dry_run
        self.step_timeout_s = step_timeout_s

    def validate_plan(self, steps: list[dict[str, Any]]) -> None:
        """Raise ToolRegistryError if any step names an unknown tool or has invalid args."""
        for s in steps:
            self.registry.validate(s["tool"], s.get("args", {}))

    async def _race(self, coro: Any, cancel: CancelToken, timeout: float) -> Any:
        """Run coro with timeout; abort promptly if cancel fires."""
        task = asyncio.ensure_future(coro)
        waiter = asyncio.ensure_future(cancel.wait())
        try:
            done, _ = await asyncio.wait({task, waiter}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return task.result()
            task.cancel()
            if waiter in done:
                raise _Cancelled()
            raise asyncio.TimeoutError()
        finally:
            waiter.cancel()
            if not task.done():
                task.cancel()

    async def _await_approval(self, eid: str, idx: int, tool_name: str, description: str,
                              cancel: CancelToken) -> bool:
        aid, fut = self.approvals.request({"execution_id": eid, "step": idx, "tool": tool_name,
                                           "description": description})
        self.bus.emit("approval_request", approval_id=aid, execution_id=eid, step=idx, tool=tool_name,
                      description=description)
        jlog.log("approval_requested", eid, tool=tool_name, step=idx)
        try:
            approved = await self._race(fut, cancel, self.approval_timeout_s)
        except asyncio.TimeoutError:
            approved = False
            self.bus.emit("approval_timeout", approval_id=aid, execution_id=eid)
        finally:
            self.approvals.discard(aid)
        self.bus.emit("approval_resolved", approval_id=aid, execution_id=eid, approved=approved)
        jlog.log("approval_resolved", eid, tool=tool_name, approved=approved)
        return approved

    async def run(self, execution_id: str, steps: list[dict[str, Any]], cancel: CancelToken,
                  approved_steps: set[int] | None = None) -> RunOutcome:
        eid = execution_id
        outcome = RunOutcome(execution_id=eid, status="succeeded")
        approved_steps = approved_steps or set()
        self.bus.set_state("executing", execution_id=eid)
        self.bus.emit("run_started", execution_id=eid, steps=[s["tool"] for s in steps], dry_run=self.dry_run)
        jlog.log("run_started", eid, steps=steps, dry_run=self.dry_run)

        try:
            self.validate_plan(steps)
        except ToolRegistryError as e:
            return self._finish(outcome, "failed", str(e))

        for idx, step in enumerate(steps):
            if cancel.cancelled:
                return self._finish(outcome, "cancelled", "Cancelled by user")
            tool, args = self.registry.validate(step["tool"], step.get("args", {}))
            args_dump = args.model_dump()
            step_id = self.db.add_step(eid, idx, tool.name, args_dump)
            self.bus.emit("step_started", execution_id=eid, step=idx, tool=tool.name, args=jlog.redact(args_dump))
            so = StepOutcome(tool=tool.name, status="running")
            outcome.steps.append(so)

            if tool.requires_approval and idx not in approved_steps:
                try:
                    ok = await self._await_approval(eid, idx, tool.name, tool.describe_approval(args), cancel)
                except _Cancelled:
                    ok = False
                if not ok:
                    so.status, so.error = "cancelled", "Not approved"
                    self.db.finish_step(step_id, so.status, 0, None, None)
                    self.bus.emit("step_finished", execution_id=eid, step=idx, tool=tool.name, status=so.status,
                                  error=so.error)
                    return self._finish(outcome, "cancelled", f"Step {idx} ({tool.name}) was not approved")

            if self.dry_run:
                so.status = "skipped_dry_run"
                so.verification = {"passed": True, "detail": "dry run: not executed"}
                self.db.finish_step(step_id, so.status, 0, None, so.verification)
                self.bus.emit("step_finished", execution_id=eid, step=idx, tool=tool.name, status=so.status)
                jlog.log("step_dry_run", eid, step=idx, tool=tool.name, args=args_dump)
                continue

            tool.ctx.execution_id = eid  # lets tools attribute LLM usage to this run
            timeout = tool.timeout_s if self.step_timeout_s is None else min(tool.timeout_s, self.step_timeout_s)
            last_err: str | None = None
            result: ToolResult | None = None
            verification: VerificationResult | None = None
            for attempt in range(1, self.max_retries + 2):
                so.attempts = attempt
                try:
                    result = await self._race(tool.run(args), cancel, timeout)
                    if not result.ok:
                        last_err = result.error or "tool reported failure"
                        verification = None
                    else:
                        verification = await self._race(tool.verify(args, result), cancel, timeout)
                        if verification.passed:
                            break
                        last_err = f"verification failed: {verification.detail}"
                except _Cancelled:
                    so.status, so.error = "cancelled", "Cancelled by user"
                    self.db.finish_step(step_id, so.status, attempt, None, None)
                    self.bus.emit("step_finished", execution_id=eid, step=idx, tool=tool.name, status=so.status)
                    return self._finish(outcome, "cancelled", "Cancelled by user")
                except asyncio.TimeoutError:
                    last_err = f"timed out after {timeout}s"
                except Exception as e:  # tool bug or backend failure: report, retry
                    last_err = f"{type(e).__name__}: {e}"
                jlog.log("step_attempt_failed", eid, step=idx, tool=tool.name, attempt=attempt, error=last_err)
                self.bus.emit("step_retry", execution_id=eid, step=idx, tool=tool.name, attempt=attempt,
                              error=last_err)
            so.result = result.model_dump() if result else None
            so.verification = verification.model_dump() if verification else None
            if verification and verification.passed:
                so.status = "succeeded"
            else:
                so.status, so.error = "failed", last_err
            self.db.finish_step(step_id, so.status, so.attempts, so.result, so.verification)
            self.bus.emit("step_finished", execution_id=eid, step=idx, tool=tool.name, status=so.status,
                          attempts=so.attempts, result=so.result, verification=so.verification, error=so.error)
            jlog.log("step_finished", eid, step=idx, tool=tool.name, status=so.status, attempts=so.attempts,
                     verification=so.verification, error=so.error)
            if so.status != "succeeded":
                return self._finish(outcome, "failed", f"Step {idx} ({tool.name}) failed: {last_err}")

        return self._finish(outcome, "succeeded", None)

    def _finish(self, outcome: RunOutcome, status: str, error: str | None) -> RunOutcome:
        outcome.status, outcome.error = status, error
        self.db.finish_execution(outcome.execution_id, status, error)
        self.bus.emit("run_finished", execution_id=outcome.execution_id, status=status, error=error, dry_run=self.dry_run)
        self.bus.set_state("error" if status == "failed" else "idle", execution_id=outcome.execution_id)
        jlog.log("run_finished", outcome.execution_id, status=status, error=error)
        return outcome
