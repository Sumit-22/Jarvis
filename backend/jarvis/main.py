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
    try:
        import pyttsx3  # noqa: F401
        from .voice.tts import TextToSpeech
        tts = TextToSpeech()
        jarvis.tts = tts  # type: ignore[attr-defined]
        jarvis.ctx.tts = tts  # type: ignore[attr-defined]
    except ImportError:
        jarvis.tts = None  # type: ignore[attr-defined]


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
        if jarvis is None:
            _optional_voice(j, settings)
            asyncio.create_task(_check_notion(j, settings))
        app.state.jarvis = j
        app.state.tasks = set()
        app.state.is_local_origin = is_local_origin
        jlog.log("startup", host=settings.host, port=settings.port, provider=settings.llm_provider,
                 dry_run=settings.dry_run)
        yield
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
