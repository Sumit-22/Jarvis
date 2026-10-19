"""System tools: speech output."""
from __future__ import annotations

from pydantic import Field

from .base import Tool, ToolInput, ToolResult, VerificationResult


class SpeakInput(ToolInput):
    text: str = Field(min_length=1, max_length=500)


class Speak(Tool):
    name = "speak"
    description = "Say a short sentence out loud (offline Windows TTS)."
    input_model = SpeakInput
    timeout_s = 30.0

    async def run(self, args: SpeakInput) -> ToolResult:
        tts = self.ctx.get("tts")
        if tts is None:
            return ToolResult(ok=False, error="TTS not available")
        await tts.speak(args.text)
        return ToolResult(ok=True)

    async def verify(self, args: SpeakInput, result: ToolResult) -> VerificationResult:
        return VerificationResult(passed=result.ok, detail="spoken without exception")
