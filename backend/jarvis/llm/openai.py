"""OpenAI-compatible chat completions provider (raw HTTP so no extra SDK is required)."""
from __future__ import annotations

import httpx

from ..config import Settings
from .provider import LLMError, LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    name = "openai"
    url = "https://api.openai.com/v1/chat/completions"

    def __init__(self, settings: Settings):
        base = settings.llm_base_url.strip().rstrip("/")
        local = base.startswith(("http://localhost", "http://127.0.0.1"))  # e.g. Ollama needs no key
        if not settings.llm_api_key and not local:
            raise LLMError("LLM_API_KEY is not set in .env")
        if not settings.llm_model:
            raise LLMError("LLM_MODEL is not set in .env")
        self.model = settings.llm_model
        self._key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else "none"
        self._custom = bool(base)
        if base:
            self.url = base + "/chat/completions"

    async def complete(self, system: str, user: str, max_tokens: int = 4096) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        # Most OpenAI-compatible servers only understand the older max_tokens field.
        body["max_tokens" if self._custom else "max_completion_tokens"] = max_tokens
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(self.url, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as e:
            raise LLMError(f"Could not reach {self.url}: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"LLM API error {r.status_code}: {r.text[:300]}")
        d = r.json()
        usage = d.get("usage") or {}
        return LLMResponse(text=d["choices"][0]["message"]["content"] or "",
                           input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
                           model=d.get("model", self.model), provider=self.name)
