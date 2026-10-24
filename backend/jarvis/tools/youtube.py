"""YouTube search and play (Playwright, main window)."""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote_plus, urlparse

from pydantic import Field

from .base import Tool, ToolInput, ToolResult, VerificationResult

RESULT_LINKS = "ytd-video-renderer a#video-title"
# YouTube keeps earlier pages in the DOM (hidden) when it navigates in-page; read only the visible one.
VISIBLE_LINKS = "ytd-search:not([hidden]) " + RESULT_LINKS
SEARCH_BOX = "input[name='search_query']"
# Plain /watch?v= links only (no Shorts, no playlists), in page order.
_HREFS_JS = """(sel) => [...document.querySelectorAll(sel)].map(a => a.getAttribute('href') || '')
    .filter(h => h.startsWith('/watch?v='))"""
# Playing = started and moving, or paused (autoplay blocked); null = no video element yet.
_PLAYBACK_JS = """() => { const v = document.querySelector('#movie_player video, video');
    if (!v) return null; return {paused: v.paused, t: v.currentTime, ready: v.readyState} }"""


def _results_cache(ctx: Any) -> dict[str, Any]:
    """Links seen by the last search_youtube. YouTube sometimes re-renders the results list after load
    (seen right after a JARVIS start), so play_youtube_result must not depend on re-reading the DOM."""
    cache = ctx.get("youtube_results")
    if cache is None:
        cache = {"url": None, "hrefs": []}
        ctx.youtube_results = cache
    return cache


class SearchYoutubeInput(ToolInput):
    query: str = Field(min_length=1, max_length=200)


class SearchYoutube(Tool):
    name = "search_youtube"
    description = "Search YouTube for a query in the main browser window."
    input_model = SearchYoutubeInput

    async def _search_in_page(self, page: Any, query: str) -> bool:
        """Use YouTube's own search box when YouTube is already open: no full page load (~2 s faster here)."""
        if "youtube.com" not in page.url:
            return False
        try:
            box = page.locator(SEARCH_BOX).first
            if not await box.count():
                return False
            before_url = page.url
            old = await page.evaluate(_HREFS_JS, VISIBLE_LINKS) if "/results" in before_url else []
            await box.fill(query, timeout=3000)
            await box.press("Enter")
            await page.wait_for_url(lambda u: "search_query=" in u and u != before_url, timeout=8000)
            # Wait for this search's results, not the previous page's.
            await page.wait_for_function(
                """([sel, old]) => { const a = document.querySelector(sel);
                    return a && a.getAttribute('href') !== old }""",
                arg=[VISIBLE_LINKS, old[0] if old else None], timeout=10000)
            return True
        except Exception:
            return False

    async def run(self, args: SearchYoutubeInput) -> ToolResult:
        page = await self.ctx.browser.page("main")
        cache = _results_cache(self.ctx)
        cache.update(url=None, hrefs=[])
        via = "search_box"
        if not await self._search_in_page(page, args.query):
            via = "goto"
            await page.goto(f"https://www.youtube.com/results?search_query={quote_plus(args.query)}",
                            wait_until="domcontentloaded")
        consent = "consent." in page.url
        hrefs: list[str] = []
        if not consent:
            try:
                await page.wait_for_selector(VISIBLE_LINKS, timeout=15000)
            except Exception:
                pass
            hrefs = await page.evaluate(_HREFS_JS, VISIBLE_LINKS)
            cache.update(url=page.url, hrefs=hrefs)
        return ToolResult(ok=True, data={"url": page.url, "results": len(hrefs), "consent_wall": consent, "via": via})

    async def verify(self, args: SearchYoutubeInput, result: ToolResult) -> VerificationResult:
        if result.data.get("consent_wall"):
            return VerificationResult(passed=False, detail="YouTube consent page shown; accept it once manually")
        n = result.data.get("results", 0)
        return VerificationResult(passed=n > 0, detail=f"{n} video links on results page")


class PlayYoutubeResultInput(ToolInput):
    index: int = Field(default=0, ge=0, le=20)


class PlayYoutubeResult(Tool):
    name = "play_youtube_result"
    description = "Open the Nth video (0-based) from the current YouTube results page."
    input_model = PlayYoutubeResultInput

    async def _href(self, page: Any, index: int) -> str | None:
        cache = _results_cache(self.ctx)
        if cache["url"] == page.url and index < len(cache["hrefs"]):
            return cache["hrefs"][index]
        if "/results" not in page.url:
            return None
        try:  # a results page JARVIS did not search itself, or more results than were cached
            await page.locator(VISIBLE_LINKS).nth(index).wait_for(state="attached", timeout=10000)
        except Exception:
            return None
        hrefs = await page.evaluate(_HREFS_JS, VISIBLE_LINKS)
        return hrefs[index] if index < len(hrefs) else None

    async def run(self, args: PlayYoutubeResultInput) -> ToolResult:
        page = await self.ctx.browser.page("main")
        href = await self._href(page, args.index)
        if href is None:
            return ToolResult(ok=False, error=f"No such result on the page ({page.url}). Run search_youtube first.")
        clicked = False
        link = page.locator(f'{VISIBLE_LINKS}[href="{href}"]').first
        try:
            # Clicking keeps YouTube's single-page app loaded: much faster than a full page load.
            if await link.count():
                await link.click(timeout=3000)
                await page.wait_for_url("**/watch?v=**", timeout=8000)
                clicked = True
        except Exception:
            clicked = False
        if not clicked:
            await page.goto(f"https://www.youtube.com{href}", wait_until="domcontentloaded")
        state = None
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:  # until the video is moving, or clearly blocked from autoplay
            state = await page.evaluate(_PLAYBACK_JS)
            if state and ((not state["paused"] and state["t"] > 0) or (state["paused"] and state["ready"] >= 3)):
                break
            await page.wait_for_timeout(100)
        has_video = state is not None
        return ToolResult(ok=True, data={"url": page.url, "has_video": has_video,
                                         "paused": state["paused"] if state else None,
                                         "via": "click" if clicked else "goto"})

    async def verify(self, args: PlayYoutubeResultInput, result: ToolResult) -> VerificationResult:
        path = urlparse(result.data.get("url", "")).path
        if path != "/watch" or not result.data.get("has_video"):
            return VerificationResult(passed=False, detail=f"not on a /watch page with a video (path={path})")
        note = " (video is paused, probably autoplay policy; press play)" if result.data.get("paused") else ""
        return VerificationResult(passed=True, detail="on /watch with a video element" + note)
