from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from jarvis.config import Settings
from jarvis.llm.provider import MockProvider
from jarvis.main import build_jarvis
from jarvis.registry.db import Database
from jarvis.tools.base import Tool, ToolResult, VerificationResult


class FakeTool(Tool):
    """Stands in for a real tool: same name/input/approval flag, no side effects."""

    def __init__(self, real: Tool, behaviour: Callable[[Any], Any] | None = None):
        super().__init__(real.ctx)
        self.name = real.name  # type: ignore[misc]
        self.description = real.description  # type: ignore[misc]
        self.input_model = real.input_model  # type: ignore[misc]
        self.requires_approval = real.requires_approval  # type: ignore[misc]
        self.uses_llm = real.uses_llm  # type: ignore[misc]
        self.retryable = real.retryable  # type: ignore[misc]
        self.timeout_s = 2.0  # type: ignore[misc]
        self.behaviour = behaviour
        self.calls: list[dict] = []

    async def run(self, args: Any) -> ToolResult:
        self.calls.append(args.model_dump())
        if self.behaviour:
            r = self.behaviour(args)
            if asyncio.iscoroutine(r):
                r = await r
            return r
        return ToolResult(ok=True, data={"fake": True})

    async def verify(self, args: Any, result: ToolResult) -> VerificationResult:
        return VerificationResult(passed=result.ok, detail="fake")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data", llm_provider="mock", approval_timeout_s=1.0,
                    step_timeout_s=2.0, tts_enabled=False, discover_apps=False)


@pytest.fixture
def make_jarvis(settings: Settings):
    def factory(responder: Callable[[str, str], str] | None = None, **overrides: Any):
        s = settings.model_copy(update=overrides)
        provider = MockProvider(responder)
        j = build_jarvis(s, provider=provider, db=Database(":memory:"))
        fakes = {}
        for name in j.registry.names():
            fake = FakeTool(j.registry.get(name))
            j.registry.register(fake)
            fakes[name] = fake
        j.fakes = fakes
        j.provider = provider
        return j
    return factory


def plan_json(*steps: tuple[str, dict], reason: str = "test") -> str:
    return json.dumps({"steps": [{"tool": t, "args": a} for t, a in steps], "reason": reason})
