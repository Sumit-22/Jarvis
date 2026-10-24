"""FastAPI app. Binds 127.0.0.1 only and serves the built dashboard."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import logging as jlog
from .adapters.ufo_adapter import DesktopAgentAdapter
from .api.routes import router as api_router
from .config import Settings, get_settings
from .executor.events import EventBus
from .llm.provider import LLMError, LLMProvider, MockProvider, build_provider
from .registry.db import Database
from .registry.seed_workflows import seed
from .router.llm_planner import LLMPlanner
from .router.router import Router
from .service import Jarvis
from .tools import build_registry
from .tools.base import ToolContext
from .tools.browser import BrowserManager

LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def is_local_origin(origin: str) -> bool:
    try:
        return urlparse(origin).hostname in LOCAL_HOSTS
    except ValueError:
        return False


def build_jarvis(settings: Settings, provider: LLMProvider | None = None, db: Database | None = None,
                 extra_ctx: dict[str, Any] | None = None) -> Jarvis:
    jlog.configure(settings.logs_dir)
    db = db or Database(settings.db_path)
    if settings.discover_apps:
        from .tools.daily import discover_start_apps, set_installed_apps
        set_installed_apps(discover_start_apps(settings.data_dir / "start_apps.json"))
    seed(db)
    if provider is None:
        try:
            provider = build_provider(settings)
        except LLMError as e:
            jlog.log("llm_provider_unavailable", error=str(e))
            provider = MockProvider()
    notion = None
    if settings.notion_token:
        from .tools.notion import NotionClient
        notion = NotionClient(settings.notion_token.get_secret_value())
    bus = EventBus()
    ctx = ToolContext(settings=settings, db=db, llm=provider, notion=notion, bus=bus,
                      browser=BrowserManager(settings.profiles_dir), ufo=DesktopAgentAdapter(settings.ufo_dir),
                      win32=None, tts=None, execution_id=None, **(extra_ctx or {}))
    registry = build_registry(ctx)
    planner = LLMPlanner(provider, registry, db, settings)
    jarvis = Jarvis(settings, db, registry, Router(db, planner), bus=bus)
    jarvis.ctx = ctx  # type: ignore[attr-defined]
    return jarvis


def _optional_voice(jarvis: Jarvis, settings: Settings) -> None:
    try:
        import faster_whisper  # noqa: F401
        from .voice.stt import SpeechToText
        jarvis.stt = SpeechToText(settings.stt_model)  # type: ignore[attr-defined]
    except ImportError:
        jarvis.stt = None  # type: ignore[attr-defined]
    from .voice.tts import TextToSpeech
    tts = TextToSpeech(jarvis.prefs)  # type: ignore[attr-defined]
    jarvis.tts = tts  # type: ignore[attr-defined]
    jarvis.ctx.tts = tts  # type: ignore[attr-defined]


def _attention(jarvis: Jarvis) -> Any:
    """While JARVIS listens for a command: pause its own YouTube video and lower the speaker volume
    (less noise for the mic, less CPU for whisper); put both back before the command runs."""
    from .tools.daily import _PAUSED_JS, _audio, _browser_video
    saved: dict[str, Any] = {}

    async def attend(on: bool) -> None:
        ctx = jarvis.ctx  # type: ignore[attr-defined]
        if on:
            page = await _browser_video(ctx)
            if page is not None and await page.evaluate(_PAUSED_JS) is False:
                await page.evaluate("() => document.querySelector('video').pause()")
                saved["page"] = page
            try:
                level, muted = await asyncio.to_thread(_audio(ctx).get)
                if level > 20 and not muted:
                    saved["level"] = level
                    await asyncio.to_thread(_audio(ctx).set_level, max(10, level // 3))
            except Exception as e:
                jlog.log("duck_failed", error=str(e))
            return
        level, page = saved.pop("level", None), saved.pop("page", None)
        if level is not None:
            await asyncio.to_thread(_audio(ctx).set_level, level)
        if page is not None:
            try:
                await page.evaluate("() => document.querySelector('video').play()")
            except Exception:
                pass

    return attend


def start_wake(jarvis: Jarvis) -> str | None:
    """Start the "Hello Archu" listener if enabled. Returns why it is not running, or None."""
    wake = getattr(jarvis, "wake", None)
    if wake is not None and wake.running:
        return None
    if getattr(jarvis, "stt", None) is None:
        return "speech to text is not installed (install.ps1 -Voice)"
    try:
        import sounddevice  # noqa: F401
    except (ImportError, OSError) as e:
        return f"sounddevice unavailable: {e}"
    from .voice.stt import SpeechToText
    from .voice.wake import WakeListener
    jarvis.wake = WakeListener(jarvis.stt, getattr(jarvis, "tts", None), jarvis.bus,  # type: ignore[attr-defined]
                               jarvis.handle_command, asyncio.get_running_loop(),
                               wake_stt=SpeechToText(jarvis.settings.wake_stt_model), attention=_attention(jarvis))
    jarvis.wake.start()  # type: ignore[attr-defined]
    jlog.log("wake_started")
    return None


async def _prewarm_browser(jarvis: Jarvis) -> None:
    """Launch the main browser window and load YouTube in the background. A command that arrives meanwhile
    simply navigates the same page; any error here is only logged."""
    try:
        page = await jarvis.ctx.browser.page("main")  # type: ignore[attr-defined]
        if page.url in ("", "about:blank"):
            await page.goto("https://www.youtube.com/", wait_until="domcontentloaded")
        jlog.log("browser_prewarmed", url=page.url)
    except Exception as e:
        jlog.log("browser_prewarm_failed", error=str(e))


async def _check_notion(jarvis: Jarvis, settings: Settings) -> None:
    notion = jarvis.ctx.notion  # type: ignore[attr-defined]
    if notion is None or not settings.notion_parent_page_id:
        return
    try:
        await notion.check_parent(settings.notion_parent_page_id)
        jlog.log("notion_parent_ok")
    except Exception as e:
        jlog.log("notion_parent_invalid", error=str(e))
        jarvis.bus.emit("warning", message=f"Notion parent page check failed: {e}")


def create_app(settings: Settings | None = None, jarvis: Jarvis | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        j = jarvis or build_jarvis(settings)
        if not hasattr(j, "prefs"):
            from .prefs import Prefs
            j.prefs = Prefs(settings.data_dir / "prefs.json")  # type: ignore[attr-defined]
        if jarvis is None:
            _optional_voice(j, settings)
            if getattr(j, "stt", None) is not None:  # load whisper in the background, not on the first command
                asyncio.create_task(asyncio.to_thread(j.stt.warm))  # type: ignore[attr-defined]
            asyncio.create_task(_check_notion(j, settings))
            if settings.browser_prewarm:
                asyncio.create_task(_prewarm_browser(j))
            if j.prefs.get("wake_enabled"):  # type: ignore[attr-defined]
                why = start_wake(j)
                if why:
                    jlog.log("wake_not_started", reason=why)
        app.state.jarvis = j
        app.state.tasks = set()
        app.state.is_local_origin = is_local_origin
        jlog.log("startup", host=settings.host, port=settings.port, provider=settings.llm_provider,
                 dry_run=settings.dry_run)
        yield
        if getattr(j, "wake", None) is not None:
            j.wake.stop()  # type: ignore[attr-defined]
        j.stop()
        browser = j.ctx.get("browser") if hasattr(j, "ctx") else None
        if browser is not None:
            await browser.close()

    app = FastAPI(title="JARVIS", lifespan=lifespan)

    @app.middleware("http")
    async def local_only(request: Request, call_next: Any) -> Any:
        origin = request.headers.get("origin")
        if origin and not is_local_origin(origin):
            return JSONResponse({"detail": "non-local origin rejected"}, status_code=403)
        client = request.client.host if request.client else ""
        if client and client not in LOCAL_HOSTS and client not in ("::1", "testclient"):
            return JSONResponse({"detail": "local connections only"}, status_code=403)
        return await call_next(request)

    app.include_router(api_router)
    if settings.frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="ui")
    return app


def run() -> None:
    import uvicorn
    s = get_settings()
    # Host is forced to loopback regardless of .env.
    uvicorn.run(create_app(s), host="127.0.0.1", port=s.port, log_level="info")


if __name__ == "__main__":
    run()
