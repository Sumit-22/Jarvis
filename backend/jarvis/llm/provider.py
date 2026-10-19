"""LLM provider interface. Planner, summaries etc. only talk to this."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

from ..config import Settings


@dataclass
class LLMResponse:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    model: str
    provider: str


class LLMError(Exception):
    pass


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    async def complete(self, system: str, user: str, max_tokens: int = 4096) -> LLMResponse: ...


class MockProvider(LLMProvider):
    """Deterministic provider for tests and for running without an API key."""

    name = "mock"

    def __init__(self, responder: Callable[[str, str], str] | None = None, model: str = "mock-model"):
        self.model = model
        self.responder = responder
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str, max_tokens: int = 4096) -> LLMResponse:
        self.calls.append((system, user))
        if self.responder is None:
            raise LLMError("No LLM configured. Set LLM_PROVIDER, LLM_MODEL and LLM_API_KEY in .env.")
        text = self.responder(system, user)
        return LLMResponse(text=text, input_tokens=len(system + user) // 4, output_tokens=len(text) // 4,
                           model=self.model, provider=self.name)


def build_provider(settings: Settings) -> LLMProvider:
    p = settings.llm_provider.lower().strip()
    if p == "anthropic":
        from .anthropic import AnthropicProvider
        return AnthropicProvider(settings)
    if p == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider(settings)
    return MockProvider()
