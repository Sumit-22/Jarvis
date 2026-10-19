"""Open claude.ai in the side browser context."""
from __future__ import annotations

from .base import Tool, ToolInput, ToolResult, VerificationResult


class OpenClaudeInput(ToolInput):
    pass


class OpenClaude(Tool):
    name = "open_claude"
    description = "Open claude.ai in the side browser window."
    input_model = OpenClaudeInput

    async def run(self, args: OpenClaudeInput) -> ToolResult:
        page = await self.ctx.browser.page("side")
        if "claude.ai" not in page.url:
            await page.goto("https://claude.ai/new", wait_until="domcontentloaded")
        needs_login = "/login" in page.url
        return ToolResult(ok=True, data={"url": page.url, "title": await page.title(), "needs_login": needs_login})

    async def verify(self, args: OpenClaudeInput, result: ToolResult) -> VerificationResult:
        url = result.data.get("url", "")
        if "claude.ai" not in url:
            return VerificationResult(passed=False, detail=f"not on claude.ai: {url}")
        note = " (login needed: log in once in the side window)" if result.data.get("needs_login") else ""
        return VerificationResult(passed=True, detail="claude.ai loaded" + note)
