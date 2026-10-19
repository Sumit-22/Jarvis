"""YouTube search and play (Playwright, main window)."""
from __future__ import annotations

from urllib.parse import quote_plus, urlparse

from pydantic import Field

from .base import Tool, ToolInput, ToolResult, VerificationResult

RESULT_LINKS = "ytd-video-renderer a#video-title"


class SearchYoutubeInput(ToolInput):
    query: str = Field(min_length=1, max_length=200)


class SearchYoutube(Tool):
    name = "search_youtube"
    description = "Search YouTube for a query in the main browser window."
    input_model = SearchYoutubeInput

    async def run(self, args: SearchYoutubeInput) -> ToolResult:
        page = await self.ctx.browser.page("main")
        await page.goto(f"https://www.youtube.com/results?search_query={quote_plus(args.query)}",
                        wait_until="domcontentloaded")
        consent = "consent." in page.url
        count = 0
        if not consent:
            try:
                await page.wait_for_selector(RESULT_LINKS, timeout=15000)
            except Exception:
                pass
            count = await page.locator(RESULT_LINKS).count()
        return ToolResult(ok=True, data={"url": page.url, "results": count, "consent_wall": consent})

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

    async def run(self, args: PlayYoutubeResultInput) -> ToolResult:
        page = await self.ctx.browser.page("main")
        links = page.locator(RESULT_LINKS)
        if await links.count() <= args.index:
            return ToolResult(ok=False, error="No such result on the page. Run search_youtube first.")
        href = await links.nth(args.index).get_attribute("href")
        await page.goto(f"https://www.youtube.com{href}", wait_until="domcontentloaded")
        try:
            await page.wait_for_selector("video", timeout=15000)
        except Exception:
            pass
        has_video = await page.locator("video").count() > 0
        paused = None
        if has_video:
            await page.wait_for_timeout(2500)
            paused = await page.evaluate("() => { const v = document.querySelector('video'); return v ? v.paused : null }")
        return ToolResult(ok=True, data={"url": page.url, "has_video": has_video, "paused": paused})

    async def verify(self, args: PlayYoutubeResultInput, result: ToolResult) -> VerificationResult:
        path = urlparse(result.data.get("url", "")).path
        if path != "/watch" or not result.data.get("has_video"):
            return VerificationResult(passed=False, detail=f"not on a /watch page with a video (path={path})")
        note = " (video is paused, probably autoplay policy; press play)" if result.data.get("paused") else ""
        return VerificationResult(passed=True, detail="on /watch with a video element" + note)
