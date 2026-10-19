"""Claude provider via the official Anthropic Python SDK."""
from __future__ import annotations

import anthropic

from ..config import Settings
from .provider import LLMError, LLMProvider, LLMResponse

# Models that accept the server-side refusal fallback ("default" routing).
_FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5")


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, settings: Settings):
        if not settings.llm_api_key:
            raise LLMError("LLM_API_KEY is not set in .env")
        self.model = settings.llm_model or "claude-opus-5-5"
        self._client = anthropic.AsyncAnthropic(api_key=settings.llm_api_key.get_secret_value(), timeout=60.0)

    async def complete(self, system: str, user: str, max_tokens: int = 4096) -> LLMResponse:
        kwargs: dict = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low"},
        )
        try:
            if self.model.startswith(_FALLBACK_MODELS):
                resp = await self._client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            else:
                resp = await self._client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            raise LLMError(f"Anthropic rate limit: {e}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Could not reach Anthropic API: {e}") from e

        if resp.stop_reason == "refusal":
            raise LLMError("The model declined this request.")
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResponse(text=text, input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                           model=resp.model, provider=self.name)
