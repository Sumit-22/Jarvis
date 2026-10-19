"""Deterministic window control with pywin32 (no LLM). Windows only; imports are lazy so tests run anywhere."""
from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import Field

from .base import Tool, ToolInput, ToolResult, VerificationResult

TOLERANCE_PX = 16  # Windows 10/11 invisible resize borders make rects differ by a few px


class Win32:
    """Thin wrapper so tests can substitute a fake."""

    def __init__(self) -> None:
        import win32api  # noqa: F401
        import win32con  # noqa: F401
        import win32gui  # noqa: F401
        import win32process  # noqa: F401
        self.api, self.con, self.gui, self.proc = win32api, win32con, win32gui, win32process

    def _exe(self, hwnd: int) -> str:
        try:
            _, pid = self.proc.GetWindowThreadProcessId(hwnd)
            h = self.api.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            try:
                return self.proc.GetModuleFileNameEx(h, 0)
            finally:
                self.api.CloseHandle(h)
        except Exception:
            return ""

    def list_windows(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def cb(hwnd: int, _: Any) -> bool:
            if self.gui.IsWindowVisible(hwnd):
                title = self.gui.GetWindowText(hwnd)
                if title:
                    out.append({"hwnd": hwnd, "title": title, "exe": self._exe(hwnd)})
            return True

        self.gui.EnumWindows(cb, None)
        return out

    def find(self, title_part: str) -> dict[str, Any] | None:
        matches = [w for w in self.list_windows() if title_part.lower() in w["title"].lower()]
        # Prefer windows owned by Playwright's Chromium over e.g. the user's own browser tab.
        matches.sort(key=lambda w: "ms-playwright" not in w["exe"].lower())
        return matches[0] if matches else None

    def work_area(self, hwnd: int) -> tuple[int, int, int, int]:
        mon = self.api.MonitorFromWindow(hwnd, self.con.MONITOR_DEFAULTTONEAREST)
        return tuple(self.api.GetMonitorInfo(mon)["Work"])  # type: ignore[return-value]

    def move(self, hwnd: int, x: int, y: int, w: int, h: int) -> None:
        self.gui.ShowWindow(hwnd, self.con.SW_RESTORE)
        self.gui.MoveWindow(hwnd, x, y, w, h, True)

    def rect(self, hwnd: int) -> tuple[int, int, int, int]:
        return self.gui.GetWindowRect(hwnd)

    def foreground(self) -> dict[str, Any]:
        hwnd = self.gui.GetForegroundWindow()
        return {"hwnd": hwnd, "title": self.gui.GetWindowText(hwnd)}

    def exists(self, hwnd: int) -> bool:
        return bool(self.gui.IsWindow(hwnd))


def halves(work: tuple[int, int, int, int]) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    l, t, r, b = work
    mid = l + (r - l) // 2
    return (l, t, mid, b), (mid, t, r, b)


def rect_close(a: tuple[int, ...], b: tuple[int, ...], tol: int = TOLERANCE_PX) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _win32(ctx: Any) -> Any:
    w = ctx.get("win32")
    if w is None:
        w = Win32()
        ctx.win32 = w
    return w


class ArrangeInput(ToolInput):
    left_title: str = Field(min_length=1)
    right_title: str = Field(min_length=1)
    layout: Literal["side_by_side"] = "side_by_side"


class ArrangeWindows(Tool):
    name = "arrange_windows"
    description = "Place two windows (matched by title substring) on the left and right halves of the screen."
    input_model = ArrangeInput

    async def run(self, args: ArrangeInput) -> ToolResult:
        w = _win32(self.ctx)

        def work() -> ToolResult:
            left, right = w.find(args.left_title), w.find(args.right_title)
            missing = [t for t, x in ((args.left_title, left), (args.right_title, right)) if x is None]
            if missing:
                return ToolResult(ok=False, error=f"window not found: {', '.join(missing)}")
            if left["hwnd"] == right["hwnd"]:
                return ToolResult(ok=False, error="both titles matched the same window")
            lt, rt = halves(w.work_area(left["hwnd"]))
            for win, (x0, y0, x1, y1) in ((left, lt), (right, rt)):
                w.move(win["hwnd"], x0, y0, x1 - x0, y1 - y0)
            return ToolResult(ok=True, data={"left": left, "right": right, "targets": {"left": lt, "right": rt}})

        return await asyncio.to_thread(work)

    async def verify(self, args: ArrangeInput, result: ToolResult) -> VerificationResult:
        w = _win32(self.ctx)
        await asyncio.sleep(0.3)
        problems = []
        for side in ("left", "right"):
            hwnd, target = result.data[side]["hwnd"], tuple(result.data["targets"][side])
            if not w.exists(hwnd):
                problems.append(f"{side} window gone")
                continue
            got = tuple(w.rect(hwnd))
            if not rect_close(got, target):
                problems.append(f"{side} rect {got} != target {target}")
        return VerificationResult(passed=not problems, detail="; ".join(problems) or "both windows at target halves")


class GetActiveWindowInput(ToolInput):
    pass


class GetActiveWindow(Tool):
    name = "get_active_window"
    description = "Return the title and handle of the foreground window."
    input_model = GetActiveWindowInput
    timeout_s = 10.0

    async def run(self, args: GetActiveWindowInput) -> ToolResult:
        return ToolResult(ok=True, data=await asyncio.to_thread(_win32(self.ctx).foreground))

    async def verify(self, args: GetActiveWindowInput, result: ToolResult) -> VerificationResult:
        return VerificationResult(passed=bool(result.data.get("hwnd")), detail=result.data.get("title", ""))


class ExpectedWindow(ToolInput):
    title: str
    position: Literal["left", "right", "any"] = "any"


class VerifyWorkspaceInput(ToolInput):
    expected_windows: list[ExpectedWindow] = Field(min_length=1)


class VerifyWorkspace(Tool):
    name = "verify_workspace"
    description = "Check that the expected windows exist and sit where expected."
    input_model = VerifyWorkspaceInput
    timeout_s = 15.0

    async def run(self, args: VerifyWorkspaceInput) -> ToolResult:
        w = _win32(self.ctx)

        def work() -> ToolResult:
            report = []
            for exp in args.expected_windows:
                win = w.find(exp.title)
                if win is None:
                    report.append({"title": exp.title, "found": False, "ok": False})
                    continue
                ok = True
                if exp.position != "any":
                    lt, rt = halves(w.work_area(win["hwnd"]))
                    ok = rect_close(tuple(w.rect(win["hwnd"])), lt if exp.position == "left" else rt)
                report.append({"title": exp.title, "found": True, "ok": ok, "window": win["title"]})
            return ToolResult(ok=True, data={"windows": report})

        return await asyncio.to_thread(work)

    async def verify(self, args: VerifyWorkspaceInput, result: ToolResult) -> VerificationResult:
        bad = [r["title"] for r in result.data["windows"] if not r["ok"]]
        return VerificationResult(passed=not bad, detail=("not ok: " + ", ".join(bad)) if bad else "workspace ok")
