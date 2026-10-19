"""Builds the tool registry. No tool may run arbitrary shell commands; there is no run_shell tool."""
from __future__ import annotations

from .base import ToolContext, ToolRegistry


def build_registry(ctx: ToolContext) -> ToolRegistry:
    from ..adapters.ufo_adapter import UfoDesktopTask
    from .browser import OpenUrl
    from .claude_web import OpenClaude
    from .leetcode import GetProblemSummary, OpenLeetcodeProblem
    from .notion import CreateNotionDbEntry, CreateNotionPage
    from .system import Speak
    from .windows import ArrangeWindows, GetActiveWindow, VerifyWorkspace
    from .youtube import PlayYoutubeResult, SearchYoutube

    reg = ToolRegistry()
    for cls in (OpenUrl, SearchYoutube, PlayYoutubeResult, OpenLeetcodeProblem, OpenClaude, GetProblemSummary,
                ArrangeWindows, GetActiveWindow, VerifyWorkspace, UfoDesktopTask, CreateNotionPage,
                CreateNotionDbEntry, Speak):
        reg.register(cls(ctx))
    return reg
