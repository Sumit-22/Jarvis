"""DesktopAgentAdapter: runs Microsoft UFO² as a subprocess in its own venv.

Launch command per UFO's docs (README "UFO² Quick Start" and quick_start_ufo2.md):
    python -m ufo --task <task_name> -r "<request>"
Logs land in <UFO dir>/logs/<task_name>/.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field

from ..tools.base import Tool, ToolInput, ToolResult, VerificationResult


@dataclass
class UfoRun:
    task_name: str
    returncode: int | None
    timed_out: bool
    stdout_tail: str
    log_dir: Path
    log_files: list[str]
    input_tokens: int | None
    output_tokens: int | None
    cost: float | None


class DesktopAgentAdapter:
    def __init__(self, ufo_dir: Path, python: Path | None = None):
        self.ufo_dir = ufo_dir
        win_py = ufo_dir / ".venv" / "Scripts" / "python.exe"
        nix_py = ufo_dir / ".venv" / "bin" / "python"
        self.python = python or (win_py if win_py.exists() else nix_py)

    def available(self) -> tuple[bool, str]:
        if not (self.ufo_dir / "ufo").is_dir():
            return False, f"UFO not found at {self.ufo_dir}"
        if not self.python.exists():
            return False, f"UFO venv python not found at {self.python}"
        if not (self.ufo_dir / "config" / "ufo" / "agents.yaml").exists():
            return False, "config/ufo/agents.yaml missing; copy it from agents.yaml.template and fill your API key"
        return True, "ok"

    def command(self, task_name: str, request: str) -> list[str]:
        return [str(self.python), "-m", "ufo", "--task", task_name, "-r", request]

    async def run(self, request: str, timeout_s: float) -> UfoRun:
        task_name = "jarvis_" + uuid.uuid4().hex[:8]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP so we can stop it
        proc = await asyncio.create_subprocess_exec(
            *self.command(task_name, request), cwd=str(self.ufo_dir), env=env,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            **kwargs,
        )
        timed_out = False
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            timed_out = isinstance(e, asyncio.TimeoutError)
            proc.kill()
            out, _ = await proc.communicate()
            if not timed_out:
                raise
        text = (out or b"").decode("utf-8", errors="replace")
        log_dir = self.ufo_dir / "logs" / task_name
        files = sorted(p.name for p in log_dir.glob("*")) if log_dir.exists() else []
        inp, outp, cost = parse_usage(log_dir, text)
        return UfoRun(task_name, proc.returncode, timed_out, text[-3000:], log_dir, files, inp, outp, cost)


def parse_usage(log_dir: Path, stdout: str) -> tuple[int | None, int | None, float | None]:
    """Best effort: UFO prints/logs cost; token counts are unknown unless found."""
    blob = stdout
    for f in list(log_dir.glob("*.log"))[:5] if log_dir.exists() else []:
        try:
            blob += f.read_text(encoding="utf-8", errors="replace")[-20000:]
        except OSError:
            pass
    cost = None
    if m := re.findall(r"[Cc]ost[^0-9$]{0,40}\$?\s*([0-9]+\.[0-9]+)", blob):
        cost = float(m[-1])
    inp = re.findall(r"prompt_tokens\"?\s*[:=]\s*([0-9]+)", blob)
    outp = re.findall(r"completion_tokens\"?\s*[:=]\s*([0-9]+)", blob)
    return (sum(map(int, inp)) if inp else None, sum(map(int, outp)) if outp else None, cost)


class UfoTaskInput(ToolInput):
    task: str = Field(min_length=3, max_length=500, description="Plain-language desktop request")
    timeout_s: float = Field(default=180, ge=10, le=900)


class UfoDesktopTask(Tool):
    name = "ufo_desktop_task"
    description = ("Hand a desktop task to Microsoft UFO² (calls an LLM every step, costs money). Use ONLY when "
                   "no other tool can do it.")
    input_model = UfoTaskInput
    requires_approval = True
    uses_llm = True
    timeout_s = 900.0

    def describe_approval(self, args: UfoTaskInput) -> str:
        return (f"Let Microsoft UFO² control your desktop for up to {args.timeout_s:.0f}s to do: \"{args.task}\". "
                "UFO sends screenshots/UI text to the LLM configured in vendor\\UFO\\config\\ufo\\agents.yaml.")

    async def run(self, args: UfoTaskInput) -> ToolResult:
        if not self.ctx.settings.ufo_enabled:
            return ToolResult(ok=False, error="UFO is disabled (UFO_ENABLED=false)")
        adapter: DesktopAgentAdapter = self.ctx.ufo
        ok, why = adapter.available()
        if not ok:
            return ToolResult(ok=False, error=why)
        timeout = min(args.timeout_s, self.ctx.settings.ufo_timeout_s)
        run = await adapter.run(args.task, timeout)
        self.ctx.db.record_usage(self.ctx.get("execution_id"), "desktop_agent", "ufo", "see agents.yaml",
                                 run.input_tokens, run.output_tokens, run.cost)
        data = {"task_name": run.task_name, "returncode": run.returncode, "timed_out": run.timed_out,
                "log_dir": str(run.log_dir), "log_files": run.log_files, "output_tail": run.stdout_tail[-1500:]}
        if run.timed_out:
            return ToolResult(ok=False, data=data, error=f"UFO timed out after {timeout:.0f}s")
        if run.returncode != 0:
            return ToolResult(ok=False, data=data, error=f"UFO exited with code {run.returncode}")
        return ToolResult(ok=True, data=data)

    async def verify(self, args: UfoTaskInput, result: ToolResult) -> VerificationResult:
        ok = result.ok and result.data.get("returncode") == 0 and bool(result.data.get("log_files"))
        return VerificationResult(passed=ok, detail=f"exit={result.data.get('returncode')}, "
                                                    f"log files={len(result.data.get('log_files', []))}")
