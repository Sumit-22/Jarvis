"""REST + WebSocket routes. Local origin only; no endpoint accepts shell commands or code."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")


def _j(request: Request) -> Any:
    return request.app.state.jarvis


class CommandIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class RunWorkflowIn(BaseModel):
    name: str
    params: dict[str, Any] = {}


class ApprovalIn(BaseModel):
    approval_id: str
    approved: bool


class SaveIn(BaseModel):
    execution_id: str
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")


class StopIn(BaseModel):
    execution_id: str | None = None


def _background(request: Request, coro: Any) -> dict[str, Any]:
    """Runs are started in the background so the UI stays responsive; results stream over the WebSocket."""
    task = asyncio.create_task(coro)
    request.app.state.tasks.add(task)
    task.add_done_callback(request.app.state.tasks.discard)
    return {"accepted": True}


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    j = _j(request)
    return {"status": "ok", "state": j.bus.state, "dry_run": j.settings.dry_run,
            "llm_provider": j.router.planner.provider.name, "llm_model": j.router.planner.provider.model,
            "llm_configured": j.router.planner.provider.name != "mock"}


@router.post("/command")
async def command(body: CommandIn, request: Request, wait: bool = False) -> dict[str, Any]:
    j = _j(request)
    if wait:
        return await j.handle_command(body.text)
    return _background(request, j.handle_command(body.text))


@router.post("/workflows/run")
async def run_workflow(body: RunWorkflowIn, request: Request, wait: bool = False) -> dict[str, Any]:
    j = _j(request)
    if wait:
        return await j.run_workflow(body.name, body.params)
    return _background(request, j.run_workflow(body.name, body.params))


@router.get("/workflows")
async def workflows(request: Request) -> list[dict[str, Any]]:
    return [w.to_dict() for w in _j(request).db.list_workflows()]


@router.post("/workflows/save")
async def save_workflow(body: SaveIn, request: Request) -> dict[str, Any]:
    try:
        return _j(request).save_from_execution(body.execution_id, body.name).to_dict()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/approve")
async def approve(body: ApprovalIn, request: Request) -> dict[str, Any]:
    ok = _j(request).approvals.resolve(body.approval_id, body.approved)
    if not ok:
        raise HTTPException(404, "No such pending approval (it may have timed out)")
    return {"ok": True}


@router.get("/approvals")
async def approvals(request: Request) -> list[dict[str, Any]]:
    return _j(request).approvals.pending()


@router.post("/stop")
async def stop(body: StopIn, request: Request) -> dict[str, Any]:
    return {"stopped": _j(request).stop(body.execution_id)}


@router.get("/executions")
async def executions(request: Request) -> list[dict[str, Any]]:
    return _j(request).db.recent_executions()


@router.get("/executions/{eid}")
async def execution(eid: str, request: Request) -> dict[str, Any]:
    ex = _j(request).db.get_execution(eid)
    if ex is None:
        raise HTTPException(404, "not found")
    ex["usage"] = _j(request).db.usage_for_execution(eid)
    return ex


@router.get("/usage")
async def usage(request: Request) -> dict[str, Any]:
    j = _j(request)
    s = j.db.usage_summary()
    s["cost_note"] = ("est_cost is null where prices are not configured (LLM_INPUT_COST_PER_MTOK / "
                      "LLM_OUTPUT_COST_PER_MTOK) or UFO did not report cost; null means unknown, not zero.")
    return s


@router.get("/tools")
async def tools(request: Request) -> list[dict[str, Any]]:
    return _j(request).registry.schemas()


@router.post("/voice")
async def voice(request: Request, audio: UploadFile = File(...)) -> dict[str, Any]:
    j = _j(request)
    stt = getattr(j, "stt", None)
    if stt is None:
        raise HTTPException(503, "Speech to text is not installed (run install.ps1 -Voice)")
    j.bus.set_state("listening")
    try:
        data = await audio.read()
        if len(data) > 15 * 1024 * 1024:
            raise HTTPException(413, "audio too large")
        suffix = "." + (audio.filename or "a.webm").rsplit(".", 1)[-1]
        result = await stt.transcribe(data, suffix=suffix)
    except HTTPException:
        j.bus.set_state("idle")
        raise
    except Exception as e:
        j.bus.set_state("error")
        raise HTTPException(500, f"transcription failed: {e}") from e
    j.bus.emit("transcript", **result)
    j.bus.set_state("idle")
    if result["text"]:
        _background(request, j.handle_command(result["text"]))
    return result


class PrefsIn(BaseModel):
    voice: str | None = None
    wake_enabled: bool | None = None


class VoiceTestIn(BaseModel):
    voice: str | None = None


def _prefs_view(j: Any) -> dict[str, Any]:
    from ..voice.tts import voice_list
    wake = getattr(j, "wake", None)
    tts = getattr(j, "tts", None)
    return {"prefs": j.prefs.all(), "voices": voice_list(),
            "wake": wake.status() if wake is not None else {"running": False, "error": None},
            "stt_available": getattr(j, "stt", None) is not None,
            "last_voice": getattr(tts, "last_voice", None), "last_fallback": getattr(tts, "last_fallback", None)}


@router.get("/prefs")
async def get_prefs(request: Request) -> dict[str, Any]:
    return await asyncio.to_thread(_prefs_view, _j(request))


@router.post("/prefs")
async def set_prefs(body: PrefsIn, request: Request) -> dict[str, Any]:
    from ..voice.tts import VOICE_IDS
    j = _j(request)
    if body.voice is not None and body.voice not in VOICE_IDS:
        raise HTTPException(400, f"unknown voice {body.voice!r}")
    j.prefs.update(voice=body.voice, wake_enabled=body.wake_enabled)
    if body.wake_enabled is not None:
        wake = getattr(j, "wake", None)
        if body.wake_enabled:
            from ..main import start_wake
            why = start_wake(j)
            if why:
                raise HTTPException(503, f"wake word unavailable: {why}")
        elif wake is not None:
            await asyncio.to_thread(wake.stop)
    view = await asyncio.to_thread(_prefs_view, j)
    j.bus.emit("prefs", **view)
    return view


@router.post("/voice/test")
async def voice_test(body: VoiceTestIn, request: Request) -> dict[str, Any]:
    from ..voice.tts import SAMPLE, VOICE_IDS
    j = _j(request)
    tts = getattr(j, "tts", None)
    if tts is None:
        raise HTTPException(503, "text to speech is not available")
    if body.voice is not None and body.voice not in VOICE_IDS:
        raise HTTPException(400, f"unknown voice {body.voice!r}")
    try:
        used = await asyncio.to_thread(tts.say_now, SAMPLE, body.voice)
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    return {"voice": used, "fallback": tts.last_fallback}


@router.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if origin and not websocket.app.state.is_local_origin(origin):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    j = websocket.app.state.jarvis
    q = j.bus.subscribe()
    try:
        await websocket.send_json({"type": "hello", "state": j.bus.state, "pending_approvals": j.approvals.pending()})
        while True:
            event = await q.get()
            await websocket.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        j.bus.unsubscribe(q)


def _updater(request: Request) -> Any:
    """One Updater per app; its progress events are handed back to the event loop (it works in a thread)."""
    upd = getattr(request.app.state, "updater", None)
    if upd is None:
        from ..updater import Updater
        bus, loop = _j(request).bus, asyncio.get_running_loop()
        upd = Updater(emit=lambda t, **k: loop.call_soon_threadsafe(lambda: bus.emit(t, **k)))
        request.app.state.updater = upd
    return upd


@router.get("/update/check")
async def update_check(request: Request) -> dict[str, Any]:
    from ..updater import UpdateError
    try:
        return await _updater(request).check()
    except UpdateError as e:
        raise HTTPException(502, f"Could not check for updates: {e}") from e


@router.post("/update/apply")
async def update_apply(request: Request) -> dict[str, Any]:
    """Starts the update in the background; progress, success and failure arrive as events."""
    from ..updater import UpdateError
    upd = _updater(request)
    if upd.busy:
        raise HTTPException(409, "an update is already running")

    async def go() -> None:
        try:
            await upd.apply()
        except UpdateError:
            pass  # already sent to the UI as update_failed

    return _background(request, go())
