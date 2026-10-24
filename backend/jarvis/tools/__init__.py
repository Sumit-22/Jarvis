"""Builds the tool registry. No tool may run arbitrary shell commands; there is no run_shell tool."""
from __future__ import annotations

from .base import ToolContext, ToolRegistry


def build_registry(ctx: ToolContext) -> ToolRegistry:
    from ..adapters.ufo_adapter import UfoDesktopTask
    from .browser import OpenUrl
    from .claude_bridge import ClaudeAsk, ClaudeStatus, ClaudeStop
    from .claude_web import OpenClaude
    from .daily import (MediaKey, OpenApp, OpenSite, PlayVisibleVideo, RotateScreen, ScrollPage, SetTimer, SetVolume,
                        SkipAd, TakeScreenshot, TellTime, VideoFullscreen, WebSearch)
    from .leetcode import GetProblemSummary, OpenLeetcodeProblem
    from .notion import CreateNotionDbEntry, CreateNotionPage
    from .system import Speak
    from .windows import ArrangeWindows, GetActiveWindow, VerifyWorkspace
    from .youtube import PlayYoutubeResult, SearchYoutube

    reg = ToolRegistry()
    for cls in (OpenUrl, SearchYoutube, PlayYoutubeResult, OpenLeetcodeProblem, OpenClaude, GetProblemSummary,
                ArrangeWindows, GetActiveWindow, VerifyWorkspace, UfoDesktopTask, CreateNotionPage,
                CreateNotionDbEntry, Speak, WebSearch, OpenSite, OpenApp, TellTime, MediaKey, SetTimer,
                TakeScreenshot, SetVolume, ScrollPage, PlayVisibleVideo, VideoFullscreen, RotateScreen, SkipAd,
                ClaudeAsk, ClaudeStatus, ClaudeStop):
        reg.register(cls(ctx))
    return reg
