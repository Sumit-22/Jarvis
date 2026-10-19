"""One long-lived Playwright instance with two persistent Chromium contexts (main, side) = two OS windows."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field

from .base import Tool, ToolInput, ToolResult, VerificationResult


class BrowserManager:
    def __init__(self, profiles_dir: Path):
        self.profiles_dir = profiles_dir
        self._pw: Any = None
        self._contexts: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def context(self, window: str) -> Any:
        async with self._lock:
            ctx = self._contexts.get(window)
            if ctx is not None:
                try:
                    _ = ctx.pages  # raises if browser was closed by the user
                    if ctx.browser is None or ctx.browser.is_connected():
                        return ctx
                except Exception:
                    pass
                self._contexts.pop(window, None)
            if self._pw is None:
                from playwright.async_api import async_playwright
                self._pw = await async_playwright().start()
            profile = self.profiles_dir / window
            profile.mkdir(parents=True, exist_ok=True)
            ctx = await self._pw.chromium.launch_persistent_context(
                str(profile), headless=False, no_viewport=True,
                args=["--no-first-run", "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required"],
            )
            ctx.on("close", lambda *_: self._contexts.pop(window, None))
            self._contexts[window] = ctx
            return ctx

    async def page(self, window: str) -> Any:
        ctx = await self.context(window)
        pages = [p for p in ctx.pages if not p.is_closed()]
        page = pages[0] if pages else await ctx.new_page()
        await page.bring_to_front()
        return page

    def current_page(self, window: str) -> Any | None:
        ctx = self._contexts.get(window)
        if ctx is None:
            return None
        pages = [p for p in ctx.pages if not p.is_closed()]
        return pages[0] if pages else None

    async def close(self) -> None:
        for ctx in list(self._contexts.values()):
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None


def host_of(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


class OpenUrlInput(ToolInput):
    url: str = Field(pattern=r"^https?://", description="Absolute http(s) URL")
    window: Literal["main", "side"] = "main"


class OpenUrl(Tool):
    name = "open_url"
    description = "Open a URL in the main or side browser window."
    input_model = OpenUrlInput

    async def run(self, args: OpenUrlInput) -> ToolResult:
        page = await self.ctx.browser.page(args.window)
        await page.goto(args.url, wait_until="domcontentloaded")
        return ToolResult(ok=True, data={"url": page.url, "title": await page.title()})

    async def verify(self, args: OpenUrlInput, result: ToolResult) -> VerificationResult:
        want, got = host_of(args.url), host_of(result.data.get("url", ""))
        ok = got == want or got.endswith("." + want)
        return VerificationResult(passed=ok, detail=f"expected host {want}, got {got}")
