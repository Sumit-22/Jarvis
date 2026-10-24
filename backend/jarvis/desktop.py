"""JARVIS desktop app: starts the backend, shows the dashboard in a native window, stops JARVIS on close.

Started by the Start-menu / Desktop shortcut that install-app.ps1 creates:
    pythonw.exe -m jarvis.desktop --data D:\\Apps\\JARVIS-data
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

URL = "http://127.0.0.1:8765/"
BACKEND_DIR = Path(__file__).resolve().parents[1]
ICON = BACKEND_DIR.parent / "assets" / "jarvis.ico"
APP_ID = "Jarvis.Desktop"  # own taskbar group and icon instead of Python's
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

LOADING = """<!doctype html><html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#03050a;
color:#8b95a7;font:15px -apple-system,'Segoe UI Variable Display','Segoe UI',sans-serif">
<div style="text-align:center"><div style="width:56px;height:56px;margin:0 auto 18px;border-radius:50%;
background:radial-gradient(circle at 30% 30%,#5ee7ff,#0a84ff 55%,#7d7aff);box-shadow:0 0 40px #0a84ff88"></div>
<div style="color:#eef2f8;font-size:17px;font-weight:600">JARVIS</div><div id="m">Starting…</div></div></body></html>"""


def _healthy() -> bool:
    try:
        with urllib.request.urlopen(URL + "api/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _user_env(name: str) -> str | None:
    """A per-user Windows env var (set with setx) even if this process started before it existed."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return None


def _backend_env(data_dir: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    for name in ("PLAYWRIGHT_BROWSERS_PATH", "HF_HOME", "PATH"):
        value = _user_env(name)
        if name == "PATH" and value:
            env["PATH"] = env.get("PATH", "") + os.pathsep + os.path.expandvars(value)  # node/npm for updates
        elif value and not env.get(name):
            env[name] = value
    if data_dir is not None:
        env["DATA_DIR"] = str(data_dir)
    return env


def _python() -> str:
    exe = Path(sys.executable)  # pythonw.exe from the shortcut; the backend runs under python.exe, hidden
    console = exe.with_name("python.exe")
    return str(console if console.exists() else exe)


def _set_window_icon(window: Any) -> None:
    """pywebview's Windows backend is a WinForms form; give it the JARVIS icon (title bar and taskbar)."""
    try:
        import clr  # pythonnet, already loaded by pywebview on Windows

        clr.AddReference("System.Drawing")
        from System import Action  # type: ignore[import-not-found]
        from System.Drawing import Icon  # type: ignore[import-not-found]

        form = window.native
        form.Invoke(Action(lambda: setattr(form, "Icon", Icon(str(ICON)))))
    except Exception:
        pass  # cosmetic only


def _kill_tree(pid: int) -> None:
    # /T also ends the backend's children (Playwright's Chromium windows).
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=_NO_WINDOW)


class App:
    def __init__(self, data_dir: Path | None):
        self.data_dir = data_dir
        self.proc: subprocess.Popen[bytes] | None = None
        self.window: Any = None
        self.restarting = False

    def start_backend(self) -> None:
        if _healthy():
            return  # a JARVIS is already running (e.g. started with start.ps1): just show it
        logs = (self.data_dir or BACKEND_DIR.parent / "data") / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        out = open(logs / "app-backend.log", "ab")  # noqa: SIM115 - handed to the child process
        self.proc = subprocess.Popen([_python(), "-m", "jarvis.main"], cwd=BACKEND_DIR, env=_backend_env(self.data_dir),
                                     stdout=out, stderr=subprocess.STDOUT, creationflags=_NO_WINDOW)

    def stop_backend(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            _kill_tree(self.proc.pid)
        self.proc = None

    def boot(self) -> None:
        """Runs once the window exists: wait for the backend, then show the dashboard."""
        _set_window_icon(self.window)
        self.start_backend()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if _healthy():
                self.window.load_url(URL)
                return
            if self.proc is not None and self.proc.poll() is not None:
                break
            time.sleep(0.3)
        log = (self.data_dir or BACKEND_DIR.parent / "data") / "logs" / "app-backend.log"
        self.window.evaluate_js(f"document.getElementById('m').textContent = "
                                f"{('JARVIS could not start. See ' + str(log)).__repr__()}")

    def restart(self) -> bool:
        """Start a fresh copy of this app (it may have been updated), then close this one."""
        self.restarting = True
        args = [sys.executable, "-m", "jarvis.desktop", "--after-restart"]
        if self.data_dir is not None:
            args += ["--data", str(self.data_dir)]
        self.stop_backend()
        subprocess.Popen(args, cwd=BACKEND_DIR, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        self.window.destroy()
        return True


class Api:
    """What the dashboard may call through window.pywebview.api. pywebview exposes every public attribute,
    so this holds only these two methods (the App is kept in a private attribute)."""

    def __init__(self, app: App):
        self._app = app

    def restart(self) -> bool:
        return self._app.restart()

    def is_desktop(self) -> bool:
        return True


def main() -> None:
    ap = argparse.ArgumentParser(prog="jarvis.desktop")
    ap.add_argument("--data", type=Path, default=None, help="folder for .env, logins and history")
    ap.add_argument("--after-restart", action="store_true")
    a = ap.parse_args()
    if a.after_restart:  # let the old backend release the port and browser profiles
        for _ in range(50):
            if not _healthy():
                break
            time.sleep(0.2)

    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    import webview

    app = App(a.data.resolve() if a.data else None)
    storage = (app.data_dir or BACKEND_DIR.parent / "data") / "webview"
    app.window = webview.create_window("JARVIS", html=LOADING, js_api=Api(app), width=1360, height=860,
                                       min_size=(380, 560), background_color="#03050a", text_select=True)
    try:
        webview.start(app.boot, private_mode=False, storage_path=str(storage))
    finally:
        if not app.restarting:
            app.stop_backend()


if __name__ == "__main__":
    main()
