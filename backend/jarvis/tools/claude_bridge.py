"""Hand a task to Claude (Claude Code CLI, or claude.ai in the side browser window), keep the same
session for follow-ups, and report back when Claude has finished.

The send step returns as soon as Claude has accepted the message; the work itself is watched in the
background, which emits `claude_update` events and speaks a one-line summary when it ends.
"""
from __future__ import annotations

import asyncio
import glob
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from .. import logging as jlog
from .base import Tool, ToolInput, ToolResult, VerificationResult

MODES = ("plan", "manual", "acceptEdits", "auto", "dontAsk")  # bypassPermissions is never offered
MODELS = ("opus", "sonnet", "haiku", "fable")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# stream-json puts whole tool results (e.g. a file Claude read) on one line; asyncio's default is 64 KB.
STREAM_LINE_LIMIT = 64 * 1024 * 1024
SYSTEM_NOTE = ("The user hears your reply through a voice assistant (JARVIS). End with one last line that starts "
               "with 'ANSWER:' and gives the result itself in one or two plain sentences, no markdown. For a "
               "question, that is the answer (e.g. 'ANSWER: daily.py defines the everyday tools: web search, "
               "apps, volume and timers.'); for a task, what is now done and anything left. Do not describe "
               "your process (no 'I read the file', 'I listed').")


# ---------- turning a spoken request into structured fields ----------

# "go to claude code and ...", "claude pe jao aur ...", "claude ko bolo ki ...", "ask claude to ..."
_INVOKE = re.compile(
    r"^(?:hey |ok )?(?:(?:go to|open|use|ask|tell|message)\s+)?claude(?P<code> code)?"
    r"(?P<web>\.ai| ai| website| web| chat| site)?(?:\s+(?:pe|par|per|on|me|mein|ko|se|to|that))?"
    r"(?:\s+(?:jao|ja ke|jaake|jakar|and|aur|to|ki|that|bolo|kaho|pucho|poocho|batao|:))*\s+", re.I)
_TAIL = re.compile(r"\s+(?:bolo|kaho|pucho|poocho|batao|karne ko bolo|karne ko kaho)$", re.I)

_DIRECTIVES: list[tuple[str, re.Pattern[str]]] = [
    ("target_code", re.compile(r"\b(on |in |to |using |with |use )?claude code( (pe|par|per|me|mein|ko|se|ke through))?\b", re.I)),
    ("target_web", re.compile(r"\b(on |in |to )?claude(\.ai| ai| website| web| chat| site)( (pe|par|per|me|mein|ko|se))?\b", re.I)),
    ("strip", re.compile(r"\b(on|in|pe|par|me|mein) claude\b", re.I)),
    ("new", re.compile(r"\b(in |on |start |open )?(a )?(new|naya|nayi|fresh) (chat|session|conversation|thread)( (start )?(karo|kro|kholo|mein|me|pe))?\b", re.I)),
    ("mode", re.compile(r"\b(in |use |using |with )?(?P<v>plan|planning|accept ?edits?|auto|manual|ask|dont ?ask) mode( (use karo|mein|me|pe|se|on))?\b", re.I)),
    ("model", re.compile(r"\b(using |with |use |on )?(the )?(claude )?(?P<v>opus|sonnet|haiku|fable)( \d(\.\d)?)?( model)?( (use karo|use kro|se|pe|mein))?\b", re.I)),
    ("project", re.compile(r"\b(in |on |for )(the |my )?(?P<v>[\w.\-]+(?: [\w.\-]+)?) (project|folder|repo|repository)( (mein|me|pe|par))?\b"
                           r"|\b(?P<v2>[\w.\-]+) (project|folder|repo) (mein|me|pe|par)\b", re.I)),
]
_LEAD = re.compile(r"^(and|aur|then|phir|to|ki|ke|that|:|,|-)\s+", re.I)
_MODE_WORDS = {"plan": "plan", "planning": "plan", "acceptedits": "acceptEdits", "acceptedit": "acceptEdits",
               "auto": "auto", "manual": "manual", "ask": "manual", "dontask": "dontAsk"}


def parse_request(text: str) -> dict[str, Any]:
    """Pull target / new-session / mode / model / project out of a spoken request; the rest is the prompt."""
    out: dict[str, Any] = {}
    rest = text.strip()
    m = _INVOKE.match(rest)
    if m:
        if m.group("code"):
            out["target"] = "code"
        elif m.group("web"):
            out["target"] = "web"
        rest = _TAIL.sub("", rest[m.end():])
    rest = f" {rest} "
    for key, rx in _DIRECTIVES:
        m = rx.search(rest)
        if not m:
            continue
        if key == "target_code":
            out.setdefault("target", "code")
        elif key == "target_web":
            out.setdefault("target", "web")
        elif key == "strip":
            pass
        elif key == "new":
            out["new_session"] = True
        elif key == "mode":
            out["mode"] = _MODE_WORDS[re.sub(r"\s", "", m.group("v").lower())]
        elif key == "model":
            out["model"] = m.group("v").lower()
        elif key == "project":
            name = (m.group("v") or m.group("v2")).strip()
            if name.lower() in {"this", "that", "the", "current", "same", "my", "our", "is", "iss", "us"}:
                continue
            out["project"] = name
        rest = rest[:m.start()] + " " + rest[m.end():]
    prompt = re.sub(r"\s+", " ", rest).strip(" ,.-:")
    for _ in range(3):
        prompt = _LEAD.sub("", prompt).strip()
    out["prompt"] = prompt
    return out


def short_summary(text: str, limit: int = 240) -> str:
    """First sentences of a reply, markdown stripped, for speech and the chat line."""
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"[#*_`>|]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[:end + 1] if end > 60 else cut.rsplit(" ", 1)[0] + "…").strip()


_ANSWER_LINE = re.compile(r"^[\s>*_`]*answer[*_`]*\s*:[*_`]*\s*(?P<a>.+?)[\s*_`]*$", re.I | re.M)


def split_answer(text: str) -> tuple[str, str | None]:
    """-> (reply without the ANSWER: line, the answer). Claude Code is asked to end with that line."""
    hits = list(_ANSWER_LINE.finditer(text))
    if not hits:
        return text.strip(), None
    m = hits[-1]
    return (text[:m.start()] + text[m.end():]).strip(), m.group("a").strip()


def spoken_answer(text: str, limit: int = 300) -> str:
    """The result itself, for speech and the chat line: the ANSWER: line if there is one, else a short
    reply as a whole, else the opening paragraph (replies usually lead with the answer)."""
    body, answer = split_answer(text)
    if answer:
        return short_summary(answer, limit)
    if len(short_summary(body, 10_000)) <= limit:
        return short_summary(body, limit)
    paras = [p for p in re.split(r"\n\s*\n", body) if p.strip() and not p.lstrip().startswith(("```", "|", "#"))]
    return short_summary(paras[0] if paras else body, limit)


# ---------- shared session state ----------

@dataclass
class ClaudeJob:
    target: str  # code | web
    prompt: str
    started: float = field(default_factory=time.time)
    status: str = "running"  # running | done | failed | stopped
    session_id: str | None = None
    url: str | None = None
    cwd: str | None = None
    mode: str | None = None
    model: str | None = None
    steps: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    plan: str | None = None
    result: str = ""
    error: str | None = None
    cost_usd: float | None = None

    @property
    def answer(self) -> str:
        """What Claude actually concluded, in a sentence or two."""
        if self.result:
            return spoken_answer(self.result)
        if self.plan:
            return "Plan ready: " + short_summary(self.plan, 240)
        return ""

    def public(self) -> dict[str, Any]:
        return {"target": self.target, "prompt": self.prompt, "status": self.status, "session_id": self.session_id,
                "url": self.url, "cwd": self.cwd, "mode": self.mode, "model": self.model, "steps": self.steps[-30:],
                "files": self.files, "plan": self.plan, "result": self.result, "error": self.error,
                "cost_usd": self.cost_usd, "answer": self.answer if self.status != "running" else "",
                "elapsed_s": round(time.time() - self.started)}


class ClaudeHub:
    """One per backend: the running job, the last finished one, and the sessions to continue."""

    def __init__(self) -> None:
        self.job: ClaudeJob | None = None
        self.last_target: str | None = None
        self.code_session: str | None = None
        self.code_cwd: str | None = None
        self.proc: Any = None
        self.task: asyncio.Task | None = None
        self.stopping = False

    @property
    def busy(self) -> bool:
        return self.job is not None and self.job.status == "running"


def _hub(ctx: Any) -> ClaudeHub:
    h = ctx.get("claude_hub")
    if h is None:
        h = ClaudeHub()
        ctx.claude_hub = h
    return h


def _emit(ctx: Any, job: ClaudeJob) -> None:
    bus = ctx.get("bus")
    if bus is not None:
        bus.emit("claude_update", **job.public())


async def _announce(ctx: Any, job: ClaudeJob) -> None:
    who = "Claude Code" if job.target == "code" else "Claude"
    if job.status == "done":
        line = job.answer or f"{who} finished without a reply."
    elif job.status == "stopped":
        line = f"{who} was stopped."
    else:
        line = f"{who} failed: {job.error or 'unknown error'}"
    job_say = line.strip()
    bus = ctx.get("bus")
    if bus is not None:
        bus.emit("claude_done", say=job_say, **job.public())
    tts = ctx.get("tts")
    settings = ctx.get("settings")
    if tts is not None and (settings is None or settings.tts_enabled):
        try:
            await tts.speak(job_say)
        except Exception:
            pass


# ---------- Claude Code CLI ----------

def find_claude_cli(configured: str = "") -> str | None:
    if configured and Path(configured).is_file():
        return configured
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    hits = glob.glob(str(Path.home() / ".vscode" / "extensions" / "anthropic.claude-code-*" / "resources"
                         / "native-binary" / "claude.exe"))
    return sorted(hits)[-1] if hits else None


def resolve_project(name: str | None, settings: Any) -> Path:
    default = Path(settings.claude_code_dir) if settings and settings.claude_code_dir else Path.cwd()
    if not name:
        return default
    root = Path(settings.claude_code_projects_dir) if settings and settings.claude_code_projects_dir else default.parent
    want = re.sub(r"[\s_\-]+", "", name.lower())
    dirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")] if root.is_dir() else []
    for d in dirs:
        if re.sub(r"[\s_\-]+", "", d.name.lower()) == want:
            return d
    from rapidfuzz import fuzz, process
    best = process.extractOne(want, {d: re.sub(r"[\s_\-]+", "", d.name.lower()) for d in dirs}, scorer=fuzz.ratio)
    if best and best[1] >= 80:
        return best[2]
    raise ValueError(f"no project folder like {name!r} in {root}")


def build_cli_args(cli: str, job: ClaudeJob, resume: str | None) -> list[str]:
    args = [cli, "-p", "--output-format", "stream-json", "--verbose", "--append-system-prompt", SYSTEM_NOTE]
    if resume:
        args += ["--resume", resume]
    if job.mode:
        args += ["--permission-mode", job.mode]
    if job.model:
        args += ["--model", job.model]
    return args


def apply_stream_event(job: ClaudeJob, ev: dict[str, Any]) -> None:
    """Fold one stream-json line from `claude -p --output-format stream-json` into the job."""
    t = ev.get("type")
    if t == "system" and ev.get("subtype") == "init":
        job.session_id = ev.get("session_id") or job.session_id
        job.model = ev.get("model") or job.model
    elif t == "assistant":
        for c in (ev.get("message") or {}).get("content") or []:
            if c.get("type") == "tool_use":
                name, inp = c.get("name", "?"), c.get("input") or {}
                target = inp.get("file_path") or inp.get("path") or inp.get("pattern") or inp.get("command") or ""
                job.steps.append(f"{name} {str(target)[:80]}".strip())
                if name in EDIT_TOOLS and inp.get("file_path") and inp["file_path"] not in job.files:
                    job.files.append(inp["file_path"])
                if name == "ExitPlanMode" and inp.get("plan"):
                    job.plan = inp["plan"]
            elif c.get("type") == "text" and c.get("text", "").strip():
                job.result = c["text"].strip()
    elif t == "result":
        job.session_id = ev.get("session_id") or job.session_id
        job.cost_usd = ev.get("total_cost_usd")
        if ev.get("result"):
            job.result = str(ev["result"]).strip()
        if ev.get("is_error") or ev.get("subtype") not in (None, "success"):
            job.status, job.error = "failed", (job.result or ev.get("subtype") or "error")[:300]
        else:
            job.status = "done"


def _child_env() -> dict[str, str]:
    # A JARVIS started from inside a Claude Code session inherits its markers; the child must not.
    return {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"))}


async def start_claude_code(ctx: Any, job: ClaudeJob, resume: str | None) -> None:
    settings = ctx.get("settings")
    cli = find_claude_cli(getattr(settings, "claude_code_bin", "") or "")
    if cli is None:
        raise RuntimeError("Claude Code CLI not found (set CLAUDE_CODE_BIN in .env)")
    spawn = ctx.get("spawn") or asyncio.create_subprocess_exec
    proc = await spawn(*build_cli_args(cli, job, resume), cwd=job.cwd, stdin=asyncio.subprocess.PIPE,
                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=_child_env(),
                       limit=STREAM_LINE_LIMIT,
                       creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0))
    proc.stdin.write(job.prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()
    hub = _hub(ctx)
    hub.proc = proc
    hub.task = asyncio.get_running_loop().create_task(_watch_code(ctx, job, proc))


async def _watch_code(ctx: Any, job: ClaudeJob, proc: Any) -> None:
    hub = _hub(ctx)
    last_emit = 0.0
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            apply_stream_event(job, ev)
            if job.session_id:
                hub.code_session = job.session_id
            if time.monotonic() - last_emit > 0.5 or ev.get("type") == "result":
                _emit(ctx, job)
                last_emit = time.monotonic()
        await proc.wait()
        if job.status == "running":
            err = (await proc.stderr.read()).decode("utf-8", "replace").strip()
            job.status = "stopped" if hub.stopping else "failed"
            job.error = job.error or (err[-300:] or f"Claude Code exited with code {proc.returncode}")
    except asyncio.CancelledError:
        job.status = "stopped"
        raise
    except Exception as e:  # never leave a job stuck at "running"
        job.status, job.error = "failed", f"lost track of Claude Code: {type(e).__name__}: {e}"[:300]
        try:
            proc.terminate()
        except Exception:
            pass
    finally:
        if job.status == "running":
            job.status, job.error = "failed", job.error or "lost track of Claude Code"
        hub.proc = None
        hub.stopping = False
        _emit(ctx, job)
        db = ctx.get("db")
        if db is not None and job.status != "running":
            db.record_usage(ctx.get("claude_execution_id"), "claude_code", "claude-code", job.model or "",
                            None, None, job.cost_usd)
        jlog.log("claude_finished", None, target="code", status=job.status, session=job.session_id,
                 files=job.files, cost_usd=job.cost_usd)
        await _announce(ctx, job)


# ---------- claude.ai in the side browser window ----------

CLAUDE_URL = "https://claude.ai"
SEL_COMPOSER = 'div[contenteditable="true"]'
SEL_SEND = 'button[aria-label="Send message"], button[aria-label="Send Message"]'
SEL_STOP = 'button[aria-label="Stop response"], button[aria-label="Stop Response"]'
SEL_USER_MSG = '[data-testid="user-message"]'
SEL_REPLY = '.font-claude-response, .font-claude-message'


def needs_login(url: str) -> bool:
    return "/login" in url or "/logout" in url


async def start_claude_web(ctx: Any, job: ClaudeJob, new_chat: bool) -> None:
    page = await ctx.browser.page("side")
    if new_chat or "/chat/" not in page.url:
        await page.goto(f"{CLAUDE_URL}/new", wait_until="domcontentloaded")
    if needs_login(page.url):
        raise RuntimeError("claude.ai wants you to sign in: run login.ps1 (JARVIS stopped) and sign in once")
    composer = page.locator(SEL_COMPOSER).first
    await composer.wait_for(state="visible", timeout=20000)
    if job.model:
        await _pick_web_model(page, job.model)
    before = await page.locator(SEL_USER_MSG).count()
    await composer.click()
    await page.keyboard.insert_text(job.prompt)
    send = page.locator(SEL_SEND).first
    if await send.count():
        await send.click()
    else:
        await page.keyboard.press("Enter")
    for _ in range(60):  # the message must appear in the chat before we call it sent
        if await page.locator(SEL_USER_MSG).count() > before:
            break
        await page.wait_for_timeout(250)
    else:
        raise RuntimeError("the message did not appear in the Claude chat")
    job.url = page.url
    hub = _hub(ctx)
    hub.task = asyncio.get_running_loop().create_task(_watch_web(ctx, job, page))


async def _pick_web_model(page: Any, model: str) -> None:
    """Best effort: open the model picker and choose the first entry containing the model name."""
    try:
        picker = page.locator('[data-testid="model-selector-dropdown"], button[aria-label*="model" i]').first
        if not await picker.count():
            return
        await picker.click()
        await page.locator('[role="menuitem"], [role="option"]').filter(has_text=re.compile(model, re.I)).first.click(timeout=4000)
    except Exception:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass


async def _watch_web(ctx: Any, job: ClaudeJob, page: Any) -> None:
    timeout = getattr(ctx.get("settings"), "claude_web_timeout_s", 900.0)
    deadline = time.monotonic() + timeout
    stable, last = 0, None
    try:
        await page.wait_for_timeout(1500)
        while time.monotonic() < deadline:
            streaming = await page.locator(SEL_STOP).count() > 0
            text = await page.evaluate(
                "(sel) => { const r = document.querySelectorAll(sel); return r.length ? r[r.length - 1].innerText : '' }",
                SEL_REPLY)
            if text != last:
                last, stable = text, 0
                job.result = text.strip()
                _emit(ctx, job)
            else:
                stable += 1
            if not streaming and job.result and stable >= 3:
                job.status = "done"
                break
            await page.wait_for_timeout(1000)
        else:
            job.status, job.error = "failed", f"no finished reply after {int(timeout)}s"
    except asyncio.CancelledError:
        job.status = "stopped"
        raise
    except Exception as e:
        job.status, job.error = "failed", f"{type(e).__name__}: {e}"
    finally:
        job.url = getattr(page, "url", job.url)
        _emit(ctx, job)
        jlog.log("claude_finished", None, target="web", status=job.status, url=job.url)
        await _announce(ctx, job)


# ---------- tools ----------

class ClaudeAskInput(ToolInput):
    prompt: str = Field(min_length=1, max_length=20000, description="The task or message for Claude")
    target: Literal["auto", "code", "web"] = Field(
        default="auto", description="code = Claude Code CLI in a project folder, web = claude.ai; auto = last used")
    new_session: bool = False
    mode: Literal["plan", "manual", "acceptEdits", "auto", "dontAsk"] | None = Field(
        default=None, description="Claude Code permission mode")
    model: Literal["opus", "sonnet", "haiku", "fable"] | None = None
    project: str | None = Field(default=None, max_length=80, description="Project folder name (Claude Code)")
    parse: bool = Field(default=False, description="Read target/mode/model/project out of the prompt text")

    @field_validator("mode", mode="before")
    @classmethod
    def _mode(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _MODE_WORDS.get(re.sub(r"[\s_]", "", v.lower()), v)
        return v

    def resolved(self) -> "ClaudeAskInput":
        if not self.parse:
            return self
        p = parse_request(self.prompt)
        data = self.model_dump()
        data.update({k: v for k, v in p.items() if v and (k == "prompt" or data.get(k) in (None, False, "auto"))})
        data["parse"] = False
        if not data["prompt"]:
            raise ValueError("what should Claude do? (the request had no task left after reading the options)")
        return ClaudeAskInput(**data)


class ClaudeAsk(Tool):
    name = "claude_ask"
    description = ("Send a task or follow-up to Claude and report back when it finishes. target=code runs Claude "
                   "Code in a project folder (can edit files; modes: plan, manual, acceptEdits, auto, dontAsk); "
                   "target=web types it into claude.ai. Follow-ups continue the same session unless new_session.")
    input_model = ClaudeAskInput
    retryable = False  # never send the same message twice
    timeout_s = 60.0

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        settings = ctx.get("settings")
        self.requires_approval = bool(getattr(settings, "claude_confirm_send", True))  # type: ignore[misc]

    def _plan(self, args: ClaudeAskInput) -> tuple[ClaudeAskInput, str]:
        a = args.resolved()
        hub = _hub(self.ctx)
        settings = self.ctx.get("settings")
        target = a.target if a.target != "auto" else (hub.last_target or getattr(settings, "claude_default_target", "code"))
        return a, target

    def describe_approval(self, args: ClaudeAskInput) -> str:
        try:
            a, target = self._plan(args)
        except ValueError as e:
            return f"Cannot send: {e}"
        hub = _hub(self.ctx)
        if target == "code":
            settings = self.ctx.get("settings")
            try:
                cwd = str(resolve_project(a.project, settings)) if a.project or a.new_session or not hub.code_cwd else hub.code_cwd
            except ValueError as e:
                cwd = f"?? {e}"
            cont = "new session" if a.new_session or not hub.code_session else f"continue session {hub.code_session[:8]}"
            mode = a.mode or getattr(settings, "claude_code_mode", "acceptEdits")
            where = f"Claude Code in {cwd}\nmode: {mode}{' · model: ' + a.model if a.model else ''} · {cont}"
        else:
            where = f"claude.ai ({'new chat' if a.new_session else 'current chat'}){' · model: ' + a.model if a.model else ''}"
        return f"Send to {where}\n\n{a.prompt}"

    async def run(self, args: ClaudeAskInput) -> ToolResult:
        try:
            a, target = self._plan(args)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))
        hub = _hub(self.ctx)
        if hub.busy:
            return ToolResult(ok=False, error="Claude is still working on the last task; say 'stop claude' first "
                                              "or wait for it to finish")
        settings = self.ctx.get("settings")
        job = ClaudeJob(target=target, prompt=a.prompt, model=a.model)
        self.ctx.claude_execution_id = self.ctx.get("execution_id")
        try:
            if target == "code":
                new = a.new_session or not hub.code_session or (a.project and str(resolve_project(a.project, settings)) != hub.code_cwd)
                job.cwd = str(resolve_project(a.project, settings)) if (a.project or new or not hub.code_cwd) else hub.code_cwd
                job.mode = a.mode or getattr(settings, "claude_code_mode", "acceptEdits")
                resume = None if new else hub.code_session
                hub.job, hub.last_target, hub.code_cwd = job, "code", job.cwd
                if new:
                    hub.code_session = None
                await start_claude_code(self.ctx, job, resume)
                for _ in range(120):  # wait for the CLI to accept it (init event) or finish fast
                    if job.session_id or job.status != "running":
                        break
                    await asyncio.sleep(0.25)
            else:
                hub.job, hub.last_target = job, "web"
                await start_claude_web(self.ctx, job, a.new_session)
        except (RuntimeError, ValueError, OSError) as e:
            job.status, job.error = "failed", str(e)
            return ToolResult(ok=False, error=str(e))
        _emit(self.ctx, job)
        who = "Claude Code" if target == "code" else "Claude"
        return ToolResult(ok=True, data={"target": target, "session_id": job.session_id, "url": job.url,
                                         "cwd": job.cwd, "mode": job.mode, "status": job.status,
                                         "say": f"Sent to {who}. I'll tell you when it's done."})

    async def verify(self, args: ClaudeAskInput, result: ToolResult) -> VerificationResult:
        d = result.data
        if d["target"] == "code":
            ok = bool(d.get("session_id")) or d.get("status") == "done"
            return VerificationResult(passed=ok, detail=f"Claude Code session {d.get('session_id') or '?'} in {d.get('cwd')} ({d.get('mode')})"
                                      if ok else "Claude Code did not start a session")
        return VerificationResult(passed=bool(d.get("url")), detail=f"message is in the chat at {d.get('url')}")


class ClaudeStatusInput(ToolInput):
    pass


class ClaudeStatus(Tool):
    name = "claude_status"
    description = "Say whether Claude is still working, and what it did or answered in the last task."
    input_model = ClaudeStatusInput
    timeout_s = 10.0

    async def run(self, args: ClaudeStatusInput) -> ToolResult:
        job = _hub(self.ctx).job
        if job is None:
            return ToolResult(ok=True, data={"say": "I haven't sent anything to Claude yet.", "job": None})
        who = "Claude Code" if job.target == "code" else "Claude"
        if job.status == "running":
            last = f" Latest step: {job.steps[-1]}." if job.steps else ""
            say = f"{who} is still working ({job.public()['elapsed_s']} seconds, {len(job.steps)} steps).{last}"
        elif job.status == "done":
            files = f" Files changed: {', '.join(Path(f).name for f in job.files[:6])}." if job.files else ""
            say = f"{job.answer or who + ' finished without a reply.'}{files}"
        else:
            say = f"{who} {job.status}: {job.error or ''}"
        return ToolResult(ok=True, data={"say": say.strip(), "job": job.public()})

    async def verify(self, args: ClaudeStatusInput, result: ToolResult) -> VerificationResult:
        return VerificationResult(passed=True, detail=result.data["say"])


class ClaudeStopInput(ToolInput):
    pass


class ClaudeStop(Tool):
    name = "claude_stop"
    description = "Stop the task Claude is working on."
    input_model = ClaudeStopInput
    timeout_s = 15.0

    async def run(self, args: ClaudeStopInput) -> ToolResult:
        hub = _hub(self.ctx)
        if not hub.busy:
            return ToolResult(ok=True, data={"was_running": False, "say": "Claude isn't working on anything."})
        if hub.job.target == "code" and hub.proc is not None:
            hub.stopping = True
            hub.proc.terminate()
        else:
            page = self.ctx.browser.current_page("side") if self.ctx.get("browser") else None
            if page is not None and await page.locator(SEL_STOP).count():
                await page.locator(SEL_STOP).first.click()
            if hub.task:
                hub.task.cancel()
        for _ in range(40):
            if not hub.busy:
                break
            await asyncio.sleep(0.25)
        return ToolResult(ok=True, data={"was_running": True, "stopped": not hub.busy, "say": "Stopped Claude."})

    async def verify(self, args: ClaudeStopInput, result: ToolResult) -> VerificationResult:
        ok = not result.data["was_running"] or result.data["stopped"]
        return VerificationResult(passed=ok, detail="nothing was running" if not result.data["was_running"]
                                  else ("stopped" if ok else "still running"))
