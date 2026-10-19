"""Record LLM usage. Cost is estimated only from prices the user configured; otherwise it is unknown (None)."""
from __future__ import annotations

from ..config import Settings
from ..registry.db import Database
from .provider import LLMResponse


def estimate_cost(settings: Settings, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if settings.llm_input_cost_per_mtok is None or settings.llm_output_cost_per_mtok is None:
        return None
    if input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * settings.llm_input_cost_per_mtok + output_tokens * settings.llm_output_cost_per_mtok) / 1e6


def record(db: Database, settings: Settings, execution_id: str | None, purpose: str, resp: LLMResponse) -> None:
    db.record_usage(execution_id, purpose, resp.provider, resp.model, resp.input_tokens, resp.output_tokens,
                    estimate_cost(settings, resp.input_tokens, resp.output_tokens) if resp.provider != "mock" else 0.0)
