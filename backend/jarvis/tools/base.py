"""Tool protocol and registry. Every tool: name, Pydantic input, approval flag, timeout, run, verify."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] = {}
    error: str | None = None


class VerificationResult(BaseModel):
    passed: bool
    detail: str = ""


class ToolContext:
    """Shared services handed to tools (browser, settings, llm, db...). Set up in main.py."""

    def __init__(self, **services: Any):
        self.__dict__.update(services)

    def get(self, name: str, default: Any = None) -> Any:
        return self.__dict__.get(name, default)


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[ToolInput]]
    requires_approval: ClassVar[bool] = False
    timeout_s: ClassVar[float] = 45.0
    # Set on tools whose every run calls an LLM (e.g. UFO); workflows containing them are flagged.
    uses_llm: ClassVar[bool] = False
    # False for tools whose side effect must not happen twice (e.g. sending a message).
    retryable: ClassVar[bool] = True

    def __init__(self, ctx: ToolContext):
        self.ctx = ctx

    @abstractmethod
    async def run(self, args: ToolInput) -> ToolResult: ...

    @abstractmethod
    async def verify(self, args: ToolInput, result: ToolResult) -> VerificationResult: ...

    def describe_approval(self, args: ToolInput) -> str:
        """Human-readable statement of exactly what will be sent and where."""
        return f"{self.name} with {args.model_dump()}"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
            "requires_approval": self.requires_approval,
        }


class ToolRegistryError(Exception):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolRegistryError(f"Unknown tool: {name!r}")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def validate(self, name: str, args: dict[str, Any]) -> tuple[Tool, ToolInput]:
        tool = self.get(name)
        try:
            return tool, tool.input_model.model_validate(args or {})
        except ValidationError as e:
            raise ToolRegistryError(f"Invalid args for {name}: {e.errors(include_url=False)}") from e

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools
