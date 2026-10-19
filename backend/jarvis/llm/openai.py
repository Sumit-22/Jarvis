"""OpenAI-compatible chat completions provider (raw HTTP so no extra SDK is required)."""
from __future__ import annotations

import httpx

from ..config import Settings
from .provider import LLMError, LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    name = "openai"
    url = "https://api.openai.com/v1/chat/completions"

    def __init__(self, settings: Settings):
        if not settings.llm_api_key:
            raise LLMError("LLM_API_KEY is not set in .env")
        if not settings.llm_model:
            raise LLMError("LLM_MODEL is not set in .env")
        self.model = settings.llm_model
        self._key = settings.llm_api_key.get_secret_value()

    async def complete(self, system: str, user: str, max_tokens: int = 4096) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_completion_tokens": max_tokens,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(self.url, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as e:
            raise LLMError(f"Could not reach OpenAI API: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"OpenAI API error {r.status_code}: {r.text[:300]}")
        d = r.json()
        usage = d.get("usage") or {}
        return LLMResponse(text=d["choices"][0]["message"]["content"] or "",
                           input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
                           model=d.get("model", self.model), provider=self.name)
