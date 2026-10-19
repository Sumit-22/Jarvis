from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from jarvis.adapters.ufo_adapter import DesktopAgentAdapter, UfoDesktopTask, UfoTaskInput
from jarvis.tools.base import ToolContext, ToolRegistryError
from jarvis.tools.browser import OpenUrlInput, host_of
from jarvis.tools.leetcode import OpenLeetcodeInput
from jarvis.tools.notion import NotionClient, NotionError, page_payload
from jarvis.tools.windows import ArrangeInput, ArrangeWindows, VerifyWorkspace, VerifyWorkspaceInput, halves

# ---------- argument validation ----------


def test_open_url_requires_http():
    OpenUrlInput(url="https://youtube.com")
    with pytest.raises(ValidationError):
        OpenUrlInput(url="file:///C:/Windows/system.ini")
    with pytest.raises(ValidationError):
        OpenUrlInput(url="https://x.com", window="third")


def test_leetcode_slug_or_url():
    assert OpenLeetcodeInput(slug="two-sum").slug == "two-sum"
    assert OpenLeetcodeInput(url="https://leetcode.com/problems/add-two-numbers/").slug == "add-two-numbers"
    with pytest.raises(ValidationError):
        OpenLeetcodeInput()
    with pytest.raises(ValidationError):
        OpenLeetcodeInput(slug="Two Sum; rm -rf")


def test_unknown_tool_and_extra_args_rejected(make_jarvis):
    j = make_jarvis()
    with pytest.raises(ToolRegistryError):
        j.registry.validate("run_shell", {"cmd": "dir"})
    with pytest.raises(ToolRegistryError):
        j.registry.validate("open_url", {"url": "https://a.com", "evil": 1})
    assert "run_shell" not in j.registry.names()


def test_host_of():
    assert host_of("https://www.youtube.com/watch?v=1") == "youtube.com"


# ---------- windows (pywin32 faked) ----------


class FakeWin32:
    def __init__(self, drift: int = 0):
        self.wins = {1: {"hwnd": 1, "title": "Two Sum - LeetCode - Chromium", "exe": "C:/ms-playwright/chrome.exe"},
                     2: {"hwnd": 2, "title": "Claude - Chromium", "exe": "C:/ms-playwright/chrome.exe"}}
        self.rects = {1: (0, 0, 800, 600), 2: (100, 100, 900, 700)}
        self.drift = drift

    def find(self, part):
        for w in self.wins.values():
            if part.lower() in w["title"].lower():
                return w
        return None

    def work_area(self, hwnd):
        return (0, 0, 1920, 1040)

    def move(self, hwnd, x, y, w, h):
        self.rects[hwnd] = (x - 7 + self.drift, y, x + w + 7, y + h + 7)  # mimic invisible borders

    def rect(self, hwnd):
        return self.rects[hwnd]

    def exists(self, hwnd):
        return hwnd in self.wins


async def test_arrange_and_verify_with_fake_win32():
    ctx = ToolContext(win32=FakeWin32())
    tool = ArrangeWindows(ctx)
    args = ArrangeInput(left_title="LeetCode", right_title="Claude")
    res = await tool.run(args)
    assert res.ok and res.data["targets"]["left"] == (0, 0, 960, 1040)
    assert (await tool.verify(args, res)).passed
    ws = VerifyWorkspace(ctx)
    wargs = VerifyWorkspaceInput(expected_windows=[{"title": "LeetCode", "position": "left"},
                                                   {"title": "Claude", "position": "right"}])
    assert (await ws.verify(wargs, await ws.run(wargs))).passed


async def test_arrange_verification_detects_wrong_rect():
    ctx = ToolContext(win32=FakeWin32(drift=200))
    tool = ArrangeWindows(ctx)
    args = ArrangeInput(left_title="LeetCode", right_title="Claude")
    res = await tool.run(args)
    assert not (await tool.verify(args, res)).passed


async def test_arrange_missing_window():
    ctx = ToolContext(win32=FakeWin32())
    res = await ArrangeWindows(ctx).run(ArrangeInput(left_title="LeetCode", right_title="Spotify"))
    assert not res.ok and "Spotify" in res.error


def test_halves():
    assert halves((0, 0, 1366, 728)) == ((0, 0, 683, 728), (683, 0, 1366, 728))


# ---------- Notion (HTTP mocked) ----------


def test_notion_payload_uses_only_user_text():
    p = page_payload("parent123", "Standup", ["line one\nline two", "x" * 2500])
    assert p["parent"] == {"page_id": "parent123"}
    assert p["properties"]["title"]["title"][0]["text"]["content"] == "Standup"
    assert len(p["children"]) == 3
    long_rich = p["children"][2]["paragraph"]["rich_text"]
    assert [len(r["text"]["content"]) for r in long_rich] == [2000, 500]


async def test_notion_create_page_ok():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": "pg1", "url": "https://notion.so/pg1"})

    c = NotionClient("secret_tok", transport=httpx.MockTransport(handler))
    r = await c.create_page("parent", "T", ["hello"])
    assert r["id"] == "pg1" and seen["auth"] == "Bearer secret_tok"
    assert seen["body"]["children"][0]["paragraph"]["rich_text"][0]["text"]["content"] == "hello"


async def test_notion_4xx_raises_with_message():
    t = httpx.MockTransport(lambda r: httpx.Response(404, json={"message": "Could not find page"}))
    with pytest.raises(NotionError, match="404: Could not find page"):
        await NotionClient("t", transport=t).create_page("p", "T", [])


async def test_notion_429_backoff_then_success():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "rate limited"})
        return httpx.Response(200, json={"id": "ok", "url": "u"})

    r = await NotionClient("t", transport=httpx.MockTransport(handler), base_delay=0).create_page("p", "T", [])
    assert r["id"] == "ok" and calls["n"] == 3


async def test_notion_429_exhausted():
    t = httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "slow"}))
    with pytest.raises(NotionError, match="429"):
        await NotionClient("t", transport=t, max_retries=2).create_page("p", "T", [])


# ---------- UFO adapter (subprocess against a stub, never real UFO) ----------


def _fake_ufo(tmp_path: Path, body: str) -> Path:
    d = tmp_path / "UFO"
    (d / "ufo").mkdir(parents=True)
    (d / "ufo" / "__init__.py").write_text("")
    (d / "ufo" / "__main__.py").write_text(textwrap.dedent(body))
    (d / "config" / "ufo").mkdir(parents=True)
    (d / "config" / "ufo" / "agents.yaml").write_text("API_KEY: placeholder\n")
    return d


OK_UFO = """
import argparse, os, pathlib
p = argparse.ArgumentParser(); p.add_argument('--task'); p.add_argument('-r', '--request')
a = p.parse_args()
d = pathlib.Path('logs') / a.task; d.mkdir(parents=True)
(d / 'response.log').write_text('{"prompt_tokens": 120, "completion_tokens": 30} Total cost: $0.0123')
print('done', a.request)
"""


async def test_ufo_adapter_success_and_usage(tmp_path, settings):
    from jarvis.registry.db import Database
    d = _fake_ufo(tmp_path, OK_UFO)
    db = Database(":memory:")
    ctx = ToolContext(settings=settings, db=db, ufo=DesktopAgentAdapter(d, python=Path(sys.executable)),
                      execution_id="ex1")
    tool = UfoDesktopTask(ctx)
    args = UfoTaskInput(task="open notepad", timeout_s=30)
    res = await tool.run(args)
    assert res.ok, res.error
    assert (await tool.verify(args, res)).passed
    u = db.usage_for_execution("ex1")[0]
    assert u["purpose"] == "desktop_agent" and u["input_tokens"] == 120 and abs(u["est_cost"] - 0.0123) < 1e-9


async def test_ufo_adapter_failure_and_timeout(tmp_path, settings):
    from jarvis.registry.db import Database
    d = _fake_ufo(tmp_path, "import sys, time\nif '--slow' in ' '.join(sys.argv): time.sleep(30)\nsys.exit(3)\n")
    ctx = ToolContext(settings=settings.model_copy(update={"ufo_timeout_s": 10}), db=Database(":memory:"),
                      ufo=DesktopAgentAdapter(d, python=Path(sys.executable)), execution_id=None)
    tool = UfoDesktopTask(ctx)
    res = await tool.run(UfoTaskInput(task="anything", timeout_s=30))
    assert not res.ok and "code 3" in res.error
    res2 = await tool.run(UfoTaskInput(task="--slow task", timeout_s=10))
    assert not res2.ok and "timed out" in res2.error


async def test_ufo_missing_reports_clearly(tmp_path, settings):
    ctx = ToolContext(settings=settings, db=None, ufo=DesktopAgentAdapter(tmp_path / "nope"), execution_id=None)
    res = await UfoDesktopTask(ctx).run(UfoTaskInput(task="open notepad"))
    assert not res.ok and "UFO not found" in res.error
