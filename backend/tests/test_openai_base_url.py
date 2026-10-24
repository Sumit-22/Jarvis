import httpx
import pytest

from jarvis.config import Settings
from jarvis.llm.openai import OpenAIProvider
from jarvis.llm.provider import LLMError


def test_default_url_needs_key():
    with pytest.raises(LLMError):
        OpenAIProvider(Settings(_env_file=None, llm_provider="openai", llm_model="m", llm_api_key=None, llm_base_url=""))


def test_local_base_url_needs_no_key():
    p = OpenAIProvider(Settings(_env_file=None, llm_provider="openai", llm_model="m", llm_api_key=None, llm_base_url="http://localhost:11434/v1/"))
    assert p.url == "http://localhost:11434/v1/chat/completions"


async def test_custom_base_url_sends_max_tokens(monkeypatch):
    sent = {}

    async def fake_post(self, url, json, headers):
        sent.update(url=url, body=json, auth=headers["Authorization"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 1}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    p = OpenAIProvider(Settings(llm_provider="openai", llm_model="gemini-2.5-flash", llm_api_key="k",
                                llm_base_url="https://generativelanguage.googleapis.com/v1beta/openai"))
    r = await p.complete("sys", "hi", max_tokens=50)
    assert sent["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert sent["body"]["max_tokens"] == 50 and "max_completion_tokens" not in sent["body"]
    assert sent["auth"] == "Bearer k" and r.text == "ok" and r.input_tokens == 3
