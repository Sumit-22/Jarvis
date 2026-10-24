"""Self-update for the installed app: fast-forward to origin/main, reinstall what changed, rebuild the dashboard.

Only runs in a clean checkout of `main` (the desktop app's own folder). It never merges, never discards local
work, and only executes fixed commands (git, pip, npm) — nothing taken from the network is run as a command.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import ROOT_DIR

BRANCH = "main"
REMOTE = "origin"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class UpdateError(Exception):
    pass


def _run(args: list[str], cwd: Path, timeout: float = 600) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # never hang on a credential prompt
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env, creationflags=_NO_WINDOW)
    except FileNotFoundError as e:
        raise UpdateError(f"{args[0]} not found") from e
    except subprocess.TimeoutExpired as e:
        raise UpdateError(f"{' '.join(args[:3])} timed out after {timeout:.0f}s") from e
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        raise UpdateError(f"{' '.join(args[:3])} failed: {' | '.join(tail)}")
    return r.stdout.strip()


def _python() -> str:
    """The venv's python.exe (the launcher runs pythonw.exe, which has no console output for pip)."""
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return str(console if console.exists() else exe)


class Updater:
    def __init__(self, root: Path = ROOT_DIR, emit: Any = None):
        self.root = root
        self.emit = emit or (lambda *a, **k: None)
        self._lock = asyncio.Lock()
        self.busy = False

    def _git(self, *args: str, timeout: float = 120) -> str:
        return _run(["git", *args], self.root, timeout)

    def _status(self, fetch: bool) -> dict[str, Any]:
        if not (self.root / ".git").exists():
            return {"supported": False, "reason": "This copy is not a git checkout, so it cannot update itself."}
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        head = self._git("log", "-1", "--format=%h|%s|%cI")
        h, subject, date = (head.split("|", 2) + ["", ""])[:3]
        base = {"branch": branch, "current": {"sha": h, "subject": subject, "date": date}, "root": str(self.root)}
        if branch != BRANCH:
            return {**base, "supported": False,
                    "reason": f"This copy is on branch '{branch}'. Updates run in the installed app, which tracks {BRANCH}."}
        if fetch:
            self._git("fetch", "--quiet", REMOTE, BRANCH)
        target = f"{REMOTE}/{BRANCH}"
        behind = int(self._git("rev-list", "--count", f"HEAD..{target}"))
        ahead = int(self._git("rev-list", "--count", f"{target}..HEAD"))
        log = self._git("log", "--format=%h|%s|%cI", "-20", f"HEAD..{target}")
        commits = [dict(zip(("sha", "subject", "date"), line.split("|", 2))) for line in log.splitlines() if line]
        dirty = bool(self._git("status", "--porcelain", "--untracked-files=no"))
        reason = None
        if dirty:
            reason = "This copy has local changes, so it will not update itself."
        elif ahead:
            reason = f"This copy has {ahead} commit(s) that are not on {BRANCH}."
        return {**base, "supported": True, "behind": behind, "ahead": ahead, "commits": commits, "dirty": dirty,
                "can_update": behind > 0 and not dirty and not ahead, "reason": reason}

    async def check(self) -> dict[str, Any]:
        async with self._lock:
            return await asyncio.to_thread(self._status, True)

    def _step(self, step: str, message: str) -> None:
        self.emit("update_progress", step=step, message=message)

    def _pip_files(self, changed: set[str]) -> list[Path]:
        """Requirement files to reinstall: only those that changed and belong to this install."""
        out = []
        for name, needed_module in (("requirements.txt", None), ("requirements-voice.txt", "faster_whisper"),
                                    ("requirements-desktop.txt", "webview")):
            if f"backend/{name}" not in changed:
                continue
            if needed_module is not None:
                try:
                    __import__(needed_module)
                except ImportError:
                    continue  # that optional part was never installed here
            out.append(self.root / "backend" / name)
        return out

    def _build_dashboard(self, reinstall: bool) -> None:
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if npm is None:
            raise UpdateError("npm not found (Node.js is needed to rebuild the dashboard)")
        front = self.root / "frontend"
        if reinstall or not (front / "node_modules").exists():
            self._step("npm", "Installing dashboard packages…")
            _run([npm, "ci", "--no-audit", "--no-fund"], front, timeout=900)
        # Build next to the live dashboard, then swap: a failed build never leaves the app without a UI.
        self._step("build", "Building the dashboard…")
        new, live, old = front / "dist.new", front / "dist", front / "dist.old"
        shutil.rmtree(new, ignore_errors=True)
        _run([npm, "run", "build", "--", "--outDir", "dist.new", "--emptyOutDir"], front, timeout=900)
        shutil.rmtree(old, ignore_errors=True)
        if live.exists():
            live.rename(old)
        new.rename(live)
        shutil.rmtree(old, ignore_errors=True)

    def _apply(self) -> dict[str, Any]:
        st = self._status(fetch=True)
        if not st["supported"] or not st["can_update"]:
            return {"ok": False, "updated": False, "message": st.get("reason") or "Already up to date.", "status": st}
        old = self._git("rev-parse", "HEAD")
        self._step("pull", f"Downloading {st['behind']} update(s)…")
        self._git("merge", "--ff-only", f"{REMOTE}/{BRANCH}")
        new = self._git("rev-parse", "HEAD")
        changed = set(self._git("diff", "--name-only", old, new).splitlines())
        try:
            for req in self._pip_files(changed):
                self._step("pip", f"Installing Python packages ({req.name})…")
                _run([_python(), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(req)],
                     self.root / "backend", timeout=900)
            if any(c.startswith("frontend/") for c in changed) or not (self.root / "frontend" / "dist").exists():
                self._build_dashboard(reinstall=bool({"frontend/package.json", "frontend/package-lock.json"} & changed))
        except UpdateError:
            # Put the code back where it was so the code and the installed packages / dashboard still match.
            self._git("reset", "--hard", old)
            raise
        self._step("done", "Update installed. Restart JARVIS to use it.")
        return {"ok": True, "updated": True, "from": old[:7], "to": new[:7], "changed": len(changed),
                "restart_required": True, "message": f"Updated {old[:7]} → {new[:7]}. Restart to finish."}

    async def apply(self) -> dict[str, Any]:
        if self._lock.locked():
            raise UpdateError("an update is already running")
        async with self._lock:
            self.busy = True
            try:
                result = await asyncio.to_thread(self._apply)
            except UpdateError as e:
                self.emit("update_failed", message=str(e))
                raise
            finally:
                self.busy = False
            self.emit("update_done", **result)
            return result
