"""Claude bridge: routing, request parsing, Claude Code sessions (CLI faked), status, stop."""
from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.tools.base import ToolContext
from jarvis.tools.claude_bridge import (ClaudeAsk, ClaudeAskInput, ClaudeHub, ClaudeStatus, ClaudeStatusInput,
                                        ClaudeStop, ClaudeStopInput, apply_stream_event, ClaudeJob, parse_request,
                                        resolve_project, split_answer, spoken_answer)

ROUTES = [
    ("claude code pe jao aur jarvis project mein plan mode use karo and add a dark mode toggle", "claude_ask"),
    ("go to claude and explain recursion", "claude_ask"),
    ("claude ko bolo ki ab tests bhi likhe", "claude_ask"),
    ("ask claude to write unit tests using opus", "claude_ask"),
    ("Jarvis, tell claude code to fix the failing test", "claude_ask"),
    ("open claude and summarise this article", "claude_ask"),
    ("new chat on claude: write a poem about rain", "claude_ask"),
    ("claude se pucho ki decorator kya hai", "claude_ask"),
    ("what did claude do", "claude_status"),
    ("claude ne kya kiya", "claude_status"),
    ("is claude done", "claude_status"),
    ("claude ka status batao", "claude_status"),
    ("claude ka kaam khatam hua", "claude_status"),
    ("stop claude", "claude_stop"),
    ("claude ko roko", "claude_stop"),
    ("open claude", "open_site"),  # just the website, no task
]


@pytest.mark.parametrize("text,workflow", ROUTES, ids=[r[0] for r in ROUTES])
def test_claude_commands_route_locally(make_jarvis, text, workflow):
    j = make_jarvis()
    d = j.router.route_local(text)
    assert d is not None and d.kind == "run" and d.workflow.name == workflow, (text, d and d.workflow and d.workflow.name)
    for s in d.steps:
        j.registry.validate(s["tool"], s["args"])


def test_prompt_keeps_words_like_jarvis_inside_the_sentence(make_jarvis):
    j = make_jarvis()
    d = j.router.route_local("Jarvis, claude ko bolo ki jarvis project ka README update kare")
    a = ClaudeAskInput(**d.steps[0]["args"]).resolved()
    assert a.prompt == "jarvis project ka README update kare"


def test_parse_request():
    p = parse_request("claude code mein auto mode se sonnet model use karo aur README update karo")
    assert p == {"target": "code", "mode": "auto", "model": "sonnet", "prompt": "README update karo"}
    p = parse_request("claude website pe new chat mein: write a poem")
    assert p == {"target": "web", "new_session": True, "prompt": "write a poem"}
    assert parse_request("tell claude code to fix the bug in this folder")["prompt"] == "fix the bug in this folder"
    assert "project" not in parse_request("tell claude code to fix the bug in this folder")


def test_spoken_answer_is_the_result_not_the_process():
    reply = ("I read the file and checked the imports.\n\n- `WebSearch`\n- `OpenApp`\n\n"
             "**ANSWER:** daily.py defines JARVIS's everyday tools: web search, sites, apps, volume and timers.")
    body, answer = split_answer(reply)
    assert answer == "daily.py defines JARVIS's everyday tools: web search, sites, apps, volume and timers."
    assert "ANSWER" not in body and "WebSearch" in body
    assert spoken_answer(reply) == answer


def test_spoken_answer_without_marker():
    assert spoken_answer("Paris is the capital of France.") == "Paris is the capital of France."
    long = "A decorator wraps a function to add behaviour.\n\n" + "More detail. " * 60
    assert spoken_answer(long) == "A decorator wraps a function to add behaviour."


def test_plan_only_reply_is_announced_as_plan():
    job = ClaudeJob(target="code", prompt="p", status="done", plan="1. Add a toggle in the header. 2. Test it.")
    assert job.answer.startswith("Plan ready: 1. Add a toggle")


def test_resolve_project(tmp_path, settings):
    (tmp_path / "Jarvis").mkdir()
    (tmp_path / "my-blog").mkdir()
    s = settings.model_copy(update={"claude_code_projects_dir": tmp_path, "claude_code_dir": tmp_path / "Jarvis"})
    assert resolve_project(None, s) == tmp_path / "Jarvis"
    assert resolve_project("jarvis", s) == tmp_path / "Jarvis"
    assert resolve_project("my blog", s) == tmp_path / "my-blog"
    with pytest.raises(ValueError):
        resolve_project("nothing like it", s)


# ---------- Claude Code with a fake CLI ----------

class FakeProc:
    def __init__(self, lines, hold=False):
        self.lines = [json.dumps(x).encode() + b"\n" for x in lines]
        self.stdin = self
        self.stdout = self
        self.stderr = self
        self.prompt = b""
        self.returncode = None
        self.hold = hold
        self.release = asyncio.Event()

    def write(self, b):
        self.prompt += b

    async def drain(self):
        pass

    def close(self):
        pass

    async def readline(self):
        if self.lines:
            await asyncio.sleep(0.01)
            return self.lines.pop(0)
        if self.hold:
            await self.release.wait()
        return b""

    async def read(self):
        return b""

    async def wait(self):
        self.returncode = 0 if not self.hold else 1
        return self.returncode

    def terminate(self):
        self.release.set()


def session_lines(sid, text, files=()):
    out = [{"type": "system", "subtype": "init", "session_id": sid, "model": "claude-opus-5-5"}]
    for f in files:
        out.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": f}}]}})
    out.append({"type": "result", "subtype": "success", "result": text, "session_id": sid, "total_cost_usd": 0.12})
    return out


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, t, **d):
        self.events.append((t, d))


def make_ctx(settings, procs, calls):
    async def spawn(*args, **kw):
        calls.append({"args": list(args), "cwd": kw.get("cwd"), "limit": kw.get("limit")})
        return procs.pop(0)
    s = settings.model_copy(update={"claude_code_bin": __file__})  # any existing file stands in for the CLI
    return ToolContext(settings=s, spawn=spawn, bus=Bus(), db=None, tts=None, execution_id="e1")


async def wait_done(ctx):
    for _ in range(200):
        if ctx.claude_hub.job and ctx.claude_hub.job.status != "running":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("job never finished")


async def test_code_task_then_follow_up_resumes_same_session(settings):
    calls = []
    p1 = FakeProc(session_lines("s-1", "Edited App.tsx.\n\nANSWER: Dark mode toggle is in the header now.", ["src/App.tsx"]))
    p2 = FakeProc(session_lines("s-1", "Tests written."))
    ctx = make_ctx(settings, [p1, p2], calls)
    tool = ClaudeAsk(ctx)
    assert tool.requires_approval and not tool.retryable

    args = ClaudeAskInput(prompt="claude code pe plan mode mein add a dark mode toggle", parse=True)
    assert "add a dark mode toggle" in tool.describe_approval(args) and "mode: plan" in tool.describe_approval(args)
    r = await tool.run(args)
    assert r.ok and (await tool.verify(args, r)).passed
    assert p1.prompt == b"add a dark mode toggle"
    assert calls[0]["args"][calls[0]["args"].index("--permission-mode") + 1] == "plan"
    assert "--resume" not in calls[0]["args"]
    await wait_done(ctx)
    done = [d for t, d in ctx.bus.events if t == "claude_done"]
    assert done and done[0]["say"] == "Dark mode toggle is in the header now." and done[0]["files"] == ["src/App.tsx"]
    assert done[0]["answer"] == "Dark mode toggle is in the header now."

    st = await ClaudeStatus(ctx).run(ClaudeStatusInput())
    assert st.data["say"] == "Dark mode toggle is in the header now. Files changed: App.tsx."

    r2 = await tool.run(ClaudeAskInput(prompt="claude ko bolo ki tests bhi likho", parse=True))
    assert r2.ok and calls[1]["args"][calls[1]["args"].index("--resume") + 1] == "s-1"
    assert calls[1]["cwd"] == calls[0]["cwd"]
    await wait_done(ctx)


async def test_new_session_does_not_resume(settings):
    calls = []
    ctx = make_ctx(settings, [FakeProc(session_lines("a", "one")), FakeProc(session_lines("b", "two"))], calls)
    tool = ClaudeAsk(ctx)
    await tool.run(ClaudeAskInput(prompt="first", target="code"))
    await wait_done(ctx)
    await tool.run(ClaudeAskInput(prompt="second", target="code", new_session=True))
    assert "--resume" not in calls[1]["args"]
    await wait_done(ctx)


async def test_busy_claude_refuses_second_task_and_stop_works(settings):
    calls = []
    proc = FakeProc([{"type": "system", "subtype": "init", "session_id": "s"}], hold=True)
    ctx = make_ctx(settings, [proc], calls)
    tool = ClaudeAsk(ctx)
    assert (await tool.run(ClaudeAskInput(prompt="long task", target="code"))).ok
    busy = await tool.run(ClaudeAskInput(prompt="another", target="code"))
    assert not busy.ok and "still working" in busy.error
    st = await ClaudeStatus(ctx).run(ClaudeStatusInput())
    assert "still working" in st.data["say"]
    stop = ClaudeStop(ctx)
    r = await stop.run(ClaudeStopInput())
    assert (await stop.verify(ClaudeStopInput(), r)).passed and ctx.claude_hub.job.status == "stopped"


async def test_cli_error_is_reported(settings):
    lines = [{"type": "system", "subtype": "init", "session_id": "x"},
             {"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "hit the turn limit"}]
    ctx = make_ctx(settings, [FakeProc(lines)], [])
    await ClaudeAsk(ctx).run(ClaudeAskInput(prompt="x", target="code"))
    await wait_done(ctx)
    assert ctx.claude_hub.job.status == "failed" and "turn limit" in ctx.claude_hub.job.error


async def test_long_stream_lines_are_read_by_the_real_subprocess(settings, tmp_path):
    """Regression: a ~100 KB tool-result line broke asyncio's default 64 KB readline limit, leaving
    the job stuck at 'running' (JARVIS kept saying 'still working'). Uses a real child process."""
    import sys
    fake_cli = tmp_path / "fake_claude.py"
    big = "x" * 100_000
    fake_cli.write_text(
        "import json, sys\nsys.stdin.read()\n"
        "print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 'big'}))\n"
        f"print(json.dumps({{'type': 'user', 'message': {{'content': [{{'type': 'tool_result', 'content': '{big}'}}]}}}}))\n"
        "print(json.dumps({'type': 'result', 'subtype': 'success', 'result': 'ANSWER: it works.', 'session_id': 'big'}))\n",
        encoding="utf-8")

    async def spawn(*args, **kw):  # run the fake CLI with the same pipes/limit the real call uses
        return await asyncio.create_subprocess_exec(sys.executable, str(fake_cli), **kw)

    s = settings.model_copy(update={"claude_code_bin": __file__, "claude_code_dir": tmp_path})
    ctx = ToolContext(settings=s, spawn=spawn, bus=Bus(), db=None, tts=None, execution_id="e1")
    assert (await ClaudeAsk(ctx).run(ClaudeAskInput(prompt="x", target="code"))).ok
    await wait_done(ctx)
    assert ctx.claude_hub.job.status == "done" and ctx.claude_hub.job.answer == "it works."


async def test_reader_failure_marks_job_failed_not_running(settings):
    class Broken(FakeProc):
        async def readline(self):
            if self.lines:
                return self.lines.pop(0)
            raise ValueError("Separator is found, but chunk is longer than limit")

    proc = Broken([{"type": "system", "subtype": "init", "session_id": "s"}])
    ctx = make_ctx(settings, [proc], [])
    await ClaudeAsk(ctx).run(ClaudeAskInput(prompt="x", target="code"))
    await wait_done(ctx)
    job = ctx.claude_hub.job
    assert job.status == "failed" and "lost track" in job.error and not ctx.claude_hub.busy
    st = await ClaudeStatus(ctx).run(ClaudeStatusInput())
    assert "still working" not in st.data["say"]


def test_plan_mode_plan_is_captured():
    job = ClaudeJob(target="code", prompt="p")
    apply_stream_event(job, {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "ExitPlanMode", "input": {"plan": "1. do x\n2. do y"}}]}})
    assert job.plan == "1. do x\n2. do y"


async def test_claude_ask_is_not_retried_and_needs_approval(make_jarvis):
    j = make_jarvis()
    r = await j.handle_command("claude code pe jao aur add a test")
    assert r["status"] == "cancelled" and j.fakes["claude_ask"].calls == []  # approval timed out, nothing sent


def test_bypass_permissions_is_not_accepted():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ClaudeAskInput(prompt="x", mode="bypassPermissions")
