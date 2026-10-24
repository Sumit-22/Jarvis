"""Everyday tools: web search, known sites and apps, clock, media keys, timers, screenshots.

All targets come from fixed allowlists below; nothing here runs a shell command.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, quote_plus, urlparse

from pydantic import Field, field_validator

from .base import Tool, ToolInput, ToolResult, VerificationResult
from .browser import host_of

# ---------- web search ----------

SEARCH_URLS = {
    "google": "https://www.google.com/search?q={q}",
    "images": "https://www.google.com/search?tbm=isch&q={q}",
    "news": "https://news.google.com/search?q={q}",
    "maps": "https://www.google.com/maps/search/{p}",
    "directions": "https://www.google.com/maps/dir/?api=1&destination={q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "github": "https://github.com/search?q={q}",
    "stackoverflow": "https://stackoverflow.com/search?q={q}",
}


class WebSearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=300)
    engine: Literal["google", "images", "news", "maps", "directions", "wikipedia", "amazon", "flipkart",
                    "github", "stackoverflow"] = "google"


def search_url(engine: str, query: str) -> str:
    return SEARCH_URLS[engine].format(q=quote_plus(query), p=quote(query))


class WebSearch(Tool):
    name = "web_search"
    description = ("Search the web in the main browser window. engine: google (default), images, news, maps, "
                   "directions, wikipedia, amazon, flipkart, github, stackoverflow.")
    input_model = WebSearchInput

    async def run(self, args: WebSearchInput) -> ToolResult:
        page = await self.ctx.browser.page("main")
        await page.goto(search_url(args.engine, args.query), wait_until="domcontentloaded")
        return ToolResult(ok=True, data={"url": page.url, "title": await page.title()})

    async def verify(self, args: WebSearchInput, result: ToolResult) -> VerificationResult:
        url = result.data.get("url", "")
        want, got = host_of(search_url(args.engine, args.query)), host_of(url)
        if "/sorry/" in urlparse(url).path:
            return VerificationResult(passed=False, detail="Google showed a captcha (unusual traffic page)")
        ok = got == want or got.endswith("." + want)
        return VerificationResult(passed=ok, detail=f"results page on {got}" if ok else f"expected {want}, got {got}")


# ---------- known websites ----------

SITES: dict[str, str] = {
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "youtube": "https://www.youtube.com",
    "youtube music": "https://music.youtube.com",
    "google drive": "https://drive.google.com",
    "google docs": "https://docs.google.com/document",
    "google sheets": "https://docs.google.com/spreadsheets",
    "google calendar": "https://calendar.google.com",
    "google maps": "https://www.google.com/maps",
    "google meet": "https://meet.google.com",
    "google photos": "https://photos.google.com",
    "google keep": "https://keep.google.com",
    "google translate": "https://translate.google.com",
    "google news": "https://news.google.com",
    "github": "https://github.com",
    "stackoverflow": "https://stackoverflow.com",
    "leetcode": "https://leetcode.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "telegram": "https://web.telegram.org",
    "linkedin": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "twitter": "https://x.com",
    "reddit": "https://www.reddit.com",
    "netflix": "https://www.netflix.com",
    "prime video": "https://www.primevideo.com",
    "hotstar": "https://www.hotstar.com",
    "spotify": "https://open.spotify.com",
    "amazon": "https://www.amazon.in",
    "flipkart": "https://www.flipkart.com",
    "notion": "https://www.notion.so",
    "outlook": "https://outlook.live.com",
    "wikipedia": "https://www.wikipedia.org",
    "weather": "https://www.google.com/search?q=weather",
}
SITE_SYNONYMS = {
    "mail": "gmail", "email": "gmail", "my email": "gmail", "my mail": "gmail", "inbox": "gmail",
    "drive": "google drive", "docs": "google docs", "sheets": "google sheets", "calendar": "google calendar",
    "my calendar": "google calendar", "maps": "google maps", "meet": "google meet", "photos": "google photos",
    "keep": "google keep", "translate": "google translate", "translator": "google translate",
    "news": "google news", "stack overflow": "stackoverflow", "chat gpt": "chatgpt", "claude ai": "claude",
    "whatsapp web": "whatsapp", "x": "twitter", "prime": "prime video", "amazon prime": "prime video",
    "jio hotstar": "hotstar", "yt": "youtube", "yt music": "youtube music", "linked in": "linkedin",
}
# After a redirect to one of these the site loaded fine but wants a sign-in.
LOGIN_HOSTS = ("accounts.google.com", "workspace.google.com", "login.live.com", "login.microsoftonline.com")

_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", re.I)


def site_names() -> list[str]:
    """Every accepted site name, longest first (for building regex alternations)."""
    return sorted(set(SITES) | set(SITE_SYNONYMS), key=lambda s: (-len(s), s))


def resolve_site(site: str) -> str:
    s = re.sub(r"\s+", " ", site.strip().lower())
    s = SITE_SYNONYMS.get(s, s)
    if s in SITES:
        return SITES[s]
    if re.match(r"^https?://\S+$", site.strip(), re.I):
        return site.strip()
    if _DOMAIN.match(s):
        return "https://" + s
    raise ValueError(f"unknown site {site!r}; use a known name, a domain like example.com, or an http(s) URL")


class OpenSiteInput(ToolInput):
    site: str = Field(min_length=1, max_length=300, description="Known site name (gmail, github...), domain or URL")

    @field_validator("site")
    @classmethod
    def _known(cls, v: str) -> str:
        resolve_site(v)
        return v


class OpenSite(Tool):
    name = "open_site"
    description = "Open a well-known website by name (gmail, github, whatsapp, chatgpt...), a domain, or a URL."
    input_model = OpenSiteInput

    async def run(self, args: OpenSiteInput) -> ToolResult:
        page = await self.ctx.browser.page("main")
        await page.goto(resolve_site(args.site), wait_until="domcontentloaded")
        return ToolResult(ok=True, data={"url": page.url, "title": await page.title()})

    async def verify(self, args: OpenSiteInput, result: ToolResult) -> VerificationResult:
        want, got = host_of(resolve_site(args.site)), host_of(result.data.get("url", ""))
        if got == want or got.endswith("." + want) or want.endswith("." + got):
            return VerificationResult(passed=True, detail=f"loaded {got}")
        if got in LOGIN_HOSTS:
            return VerificationResult(passed=True, detail=f"loaded, but {got} asks you to sign in")
        return VerificationResult(passed=False, detail=f"expected {want}, got {got}")


# ---------- desktop apps and folders ----------

# name -> (ShellExecute target, window-title keyword used to verify; "class:X" matches the window class instead)
APPS: dict[str, tuple[str, str]] = {
    "notepad": ("notepad.exe", "Notepad"),
    "calculator": ("calc.exe", "Calculator"),
    "paint": ("mspaint.exe", "Paint"),
    "file explorer": ("explorer.exe", "class:CabinetWClass"),
    "settings": ("ms-settings:", "Settings"),
    "snipping tool": ("snippingtool.exe", "Snipping Tool"),
    "camera": ("microsoft.windows.camera:", "Camera"),
    "clock": ("ms-clock:", "Clock"),
    "microsoft store": ("ms-windows-store:", "Microsoft Store"),
    "control panel": ("control.exe", "Control Panel"),
    "word": ("winword", "Word"),
    "excel": ("excel", "Excel"),
    "powerpoint": ("powerpnt", "PowerPoint"),
    "edge": ("msedge", "Edge"),
    "chrome": ("chrome", "Chrome"),
    "vs code": ("vscode:", "Visual Studio Code"),
}
APP_SYNONYMS = {
    "calc": "calculator", "explorer": "file explorer", "my files": "file explorer", "files": "file explorer",
    "this pc": "file explorer", "windows settings": "settings", "pc settings": "settings",
    "screenshot tool": "snipping tool", "snip": "snipping tool", "alarm": "clock", "alarms": "clock",
    "timer app": "clock", "store": "microsoft store", "ms word": "word", "microsoft word": "word",
    "ms excel": "excel", "microsoft excel": "excel", "ppt": "powerpoint", "microsoft edge": "edge",
    "google chrome": "chrome", "vscode": "vs code", "visual studio code": "vs code", "code editor": "vs code",
    "mspaint": "paint", "webcam": "camera",
}
FOLDERS = ("downloads", "documents", "desktop", "pictures", "music", "videos")

# Start-menu apps found on this PC (normalized name -> AppUserModelID), filled by set_installed_apps().
INSTALLED_APPS: dict[str, str] = {}
_JUNK_APP = re.compile(r"\b(uninstall|readme|read me|help|documentation|release notes|license|website|manual)\b"
                       r"|\.(chm|txt|url|html?|pdf)$", re.I)


def app_key(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s\-]", " ", name.lower())).strip()


def set_installed_apps(apps: dict[str, str]) -> None:
    """apps: display name -> AppUserModelID (as Get-StartApps returns them)."""
    INSTALLED_APPS.clear()
    for name, app_id in apps.items():
        key = app_key(name)
        if len(key) >= 2 and not _JUNK_APP.search(name) and not _JUNK_APP.search(app_id):
            INSTALLED_APPS.setdefault(key, app_id)


def discover_start_apps(cache: Path) -> dict[str, str]:
    """List Start-menu apps with the fixed cmdlet Get-StartApps (no user input reaches the shell).

    Falls back to the last cached list if PowerShell fails.
    """
    import json
    import subprocess
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        rows = json.loads(out or "[]")
        apps = {r["Name"]: r["AppID"] for r in (rows if isinstance(rows, list) else [rows])}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(apps, indent=0), encoding="utf-8")
        return apps
    except Exception:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            return {}


def app_names() -> list[str]:
    names = set(APPS) | set(APP_SYNONYMS) | set(FOLDERS) | {f"{f} folder" for f in FOLDERS} | {f"my {f}" for f in FOLDERS}
    return sorted(names, key=lambda s: (-len(s), s))


def installed_app_names() -> list[str]:
    return sorted(set(INSTALLED_APPS) - set(app_names()), key=lambda s: (-len(s), s))


def resolve_app(app: str) -> tuple[str, str, str]:
    """-> (canonical name, ShellExecute target, verify keyword). Allowlist and folders first, then Start-menu apps."""
    a = re.sub(r"\s+", " ", app.strip().lower())
    a = APP_SYNONYMS.get(a, a)
    folder = re.sub(r"^my |( folder)$", "", a)
    if folder in FOLDERS:
        return folder, str(Path.home() / folder.capitalize()), folder.capitalize()
    if a in APPS:
        return (a, *APPS[a])
    key = app_key(a)
    if key not in INSTALLED_APPS and INSTALLED_APPS:
        from rapidfuzz import fuzz, process
        best = process.extractOne(key, list(INSTALLED_APPS), scorer=fuzz.WRatio)
        if best and best[1] >= 88:
            key = best[0]
    if key in INSTALLED_APPS:
        return key, "shell:AppsFolder\\" + INSTALLED_APPS[key], "new:" + key
    raise ValueError(f"no app called {app!r} in the allowlist or the Start menu")


class OpenAppInput(ToolInput):
    app: str = Field(min_length=1, max_length=80)

    @field_validator("app")
    @classmethod
    def _known(cls, v: str) -> str:
        resolve_app(v)
        return v


def _launch(target: str) -> None:
    os.startfile(target)  # type: ignore[attr-defined]  # Windows only; target is from the allowlist or Start menu


def _title_words(name: str) -> list[str]:
    return [w for w in name.split() if len(w) >= 3 and w not in {"the", "for", "and", "app", "microsoft", "windows"}]


class OpenApp(Tool):
    name = "open_app"
    description = ("Open a Windows app: notepad, calculator, paint, file explorer, settings, camera, clock, word, "
                   "excel, powerpoint, edge, chrome, vs code, a user folder (downloads, documents...), or any app "
                   "installed in the Start menu by its name.")
    input_model = OpenAppInput
    timeout_s = 30.0

    async def run(self, args: OpenAppInput) -> ToolResult:
        from .windows import _win32
        name, target, keyword = resolve_app(args.app)
        try:
            self._before = {x["hwnd"] for x in await asyncio.to_thread(_win32(self.ctx).list_windows)}
        except Exception:
            self._before = set()
        launch = self.ctx.get("launcher") or _launch
        try:
            await asyncio.to_thread(launch, target)
        except OSError as e:
            return ToolResult(ok=False, error=f"could not start {name} (is it installed?): {e}")
        return ToolResult(ok=True, data={"app": name, "keyword": keyword})

    async def verify(self, args: OpenAppInput, result: ToolResult) -> VerificationResult:
        from .windows import _win32
        w = _win32(self.ctx)
        keyword = result.data["keyword"].lower()
        started = keyword.startswith("new:")
        if started:  # Start-menu app: its name in a window title, else any window that was not there before
            words, field, wait = _title_words(keyword[4:]) or [keyword[4:]], "title", 15
        elif keyword.startswith("class:"):
            words, field, wait = [keyword[6:]], "class", 10
        else:
            words, field, wait = [keyword], "title", 10
        before = getattr(self, "_before", set())
        deadline = time.monotonic() + wait
        while True:
            wins = await asyncio.to_thread(w.list_windows)
            hit = next((x for x in wins if any(k in x.get(field, "").lower() for k in words)), None)
            new = next((x for x in wins if started and before and x["hwnd"] not in before), None)
            if hit or time.monotonic() > deadline:
                break
            await asyncio.sleep(0.5)
        if hit:
            return VerificationResult(passed=True, detail=f"window open: {hit['title']}")
        if new:
            return VerificationResult(passed=True, detail=f"new window appeared: {new['title']}")
        return VerificationResult(passed=False, detail=f"no window matching {field} {words}")


# ---------- clock ----------

class TellTimeInput(ToolInput):
    what: Literal["time", "date", "both"] = "time"

    @field_validator("what", mode="before")
    @classmethod
    def _map(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip().lower()
            return {"day": "date", "today": "date", "din": "date", "tareekh": "date"}.get(v, v)
        return v


def describe_now(what: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    t = now.strftime("%I:%M %p").lstrip("0")
    d = f"{now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}"
    return {"time": f"It's {t}.", "date": f"Today is {d}.", "both": f"It's {t} on {d}."}[what]


class TellTime(Tool):
    name = "tell_time"
    description = "Tell the current local time and/or date (read from this PC's clock)."
    input_model = TellTimeInput
    timeout_s = 5.0

    async def run(self, args: TellTimeInput) -> ToolResult:
        return ToolResult(ok=True, data={"say": describe_now(args.what)})

    async def verify(self, args: TellTimeInput, result: ToolResult) -> VerificationResult:
        return VerificationResult(passed=bool(result.data.get("say")), detail=result.data.get("say", ""))


# ---------- media keys, volume, playback ----------

VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2,
      "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}
MEDIA_SYNONYMS = {
    "pause": "pause", "resume": "play", "play": "play", "unpause": "play", "play pause": "play_pause",
    "skip": "next", "next song": "next", "next track": "next", "prev": "previous",
    "back": "previous", "louder": "volume_up", "increase": "volume_up", "raise": "volume_up", "turn up": "volume_up",
    "up": "volume_up", "volume up": "volume_up", "quieter": "volume_down", "decrease": "volume_down",
    "lower": "volume_down", "turn down": "volume_down", "down": "volume_down", "volume down": "volume_down",
    "mute volume": "mute",
    # Hinglish
    "badhao": "volume_up", "tez karo": "volume_up", "kam karo": "volume_down", "kam kro": "volume_down",
    "dheere karo": "volume_down", "band karo": "mute", "roko": "pause", "rok do": "pause",
    "chalao": "play", "pause karo": "pause", "agla": "next", "pichla": "previous",
    "pause kar do": "pause", "play karo": "play", "play kar do": "play", "resume karo": "play",
    "wapas chalao": "play", "phir se chalao": "play",
}
VOLUME_STEP = 10  # percent per "volume up/down"


class Audio:
    """Default speaker volume through Windows Core Audio (pycaw). Each call runs in a worker thread."""

    def _ep(self) -> Any:
        import comtypes
        from pycaw.pycaw import AudioUtilities
        comtypes.CoInitialize()
        return AudioUtilities.GetSpeakers().EndpointVolume

    def get(self) -> tuple[int, bool]:
        ep = self._ep()
        return round(ep.GetMasterVolumeLevelScalar() * 100), bool(ep.GetMute())

    def set_level(self, pct: int) -> None:
        self._ep().SetMasterVolumeLevelScalar(max(0, min(100, pct)) / 100, None)

    def set_mute(self, muted: bool) -> None:
        self._ep().SetMute(int(muted), None)


def _audio(ctx: Any) -> Any:
    a = ctx.get("audio")
    if a is None:
        a = Audio()
        ctx.audio = a
    return a


async def _browser_video(ctx: Any) -> Any:
    """JARVIS's own browser page if it is showing a <video> (e.g. YouTube), else None."""
    browser = ctx.get("browser")
    page = browser.current_page("main") if browser is not None else None
    if page is None:
        return None
    try:
        return page if await page.evaluate("() => !!document.querySelector('video')") else None
    except Exception:
        return None


_PAUSED_JS = "() => { const v = document.querySelector('video'); return v ? v.paused : null }"


class MediaKeyInput(ToolInput):
    action: Literal["play", "pause", "play_pause", "next", "previous", "stop", "volume_up", "volume_down",
                    "mute", "unmute"]
    times: int | None = Field(default=None, ge=1, le=10, description="Repeat count; volume moves 10% per step")

    @field_validator("action", mode="before")
    @classmethod
    def _map(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = re.sub(r"\s+", " ", v.strip().lower())
            return MEDIA_SYNONYMS.get(v, v.replace(" ", "_"))
        return v


def _press(vk: int, times: int) -> None:
    import win32api
    import win32con
    for _ in range(times):
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_EXTENDEDKEY, 0)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_EXTENDEDKEY | win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.03)


class MediaKey(Tool):
    name = "media_key"
    description = ("Media and volume control: play, pause, play_pause, next, previous, stop, volume_up, volume_down "
                   "(10% per step), mute, unmute. Controls JARVIS's YouTube video directly when one is open, "
                   "otherwise sends the Windows media key.")
    input_model = MediaKeyInput
    timeout_s = 20.0

    async def run(self, args: MediaKeyInput) -> ToolResult:
        a, n = args.action, args.times or 1
        if a in ("volume_up", "volume_down", "mute", "unmute"):
            audio = _audio(self.ctx)
            before = await asyncio.to_thread(audio.get)
            if a == "volume_up":
                await asyncio.to_thread(audio.set_level, before[0] + VOLUME_STEP * n)
                if before[1]:
                    await asyncio.to_thread(audio.set_mute, False)
            elif a == "volume_down":
                await asyncio.to_thread(audio.set_level, before[0] - VOLUME_STEP * n)
            else:
                await asyncio.to_thread(audio.set_mute, a == "mute")
            after = await asyncio.to_thread(audio.get)
            state = f"{after[0]}%{' (muted)' if after[1] else ''}"
            return ToolResult(ok=True, data={"action": a, "before": list(before), "after": list(after),
                                             "say": f"Volume {state}."})

        page = await _browser_video(self.ctx)
        if page is not None and a in ("play", "pause", "play_pause", "stop"):
            before = await page.evaluate(_PAUSED_JS)
            want_paused = {"play": False, "pause": True, "stop": True}.get(a, not before)
            await page.evaluate("(p) => { const v = document.querySelector('video'); p ? v.pause() : v.play() }",
                                want_paused)
            after = await page.evaluate(_PAUSED_JS)
            for i in range(1, 31):  # read back until the player reports the new state (usually < 0.2 s)
                if after == want_paused:
                    break
                if i % 10 == 0:  # a video that is still starting up can undo the first pause(); ask again
                    await page.evaluate("(p) => { const v = document.querySelector('video'); "
                                        "p ? v.pause() : v.play() }", want_paused)
                await page.wait_for_timeout(100)
                after = await page.evaluate(_PAUSED_JS)
            return ToolResult(ok=True, data={"action": a, "via": "browser", "want_paused": want_paused,
                                             "paused": after, "url": page.url})
        if page is not None and a in ("next", "previous") and "youtube.com/watch" in page.url:
            before_url = page.url
            if a == "next":
                await page.bring_to_front()
                await page.keyboard.press("Shift+N")
            else:
                await page.go_back(wait_until="domcontentloaded")
            for _ in range(20):
                if page.url != before_url:
                    break
                await page.wait_for_timeout(250)
            return ToolResult(ok=True, data={"action": a, "via": "browser", "before_url": before_url, "url": page.url})

        press = self.ctx.get("key_presser") or _press
        vk = VK["play_pause" if a in ("play", "pause") else a]
        await asyncio.to_thread(press, vk, n)
        return ToolResult(ok=True, data={"action": a, "via": "media_key", "times": n})

    async def verify(self, args: MediaKeyInput, result: ToolResult) -> VerificationResult:
        d, a = result.data, args.action
        if "after" in d:  # volume, read back from Windows
            (v0, m0), (v1, m1) = d["before"], d["after"]
            ok = {"volume_up": v1 > v0 or v0 >= 100, "volume_down": v1 < v0 or v0 <= 0,
                  "mute": m1, "unmute": not m1}[a]
            return VerificationResult(passed=ok, detail=f"volume {v0}%{' muted' if m0 else ''} -> "
                                                        f"{v1}%{' muted' if m1 else ''}")
        if d.get("via") == "browser" and "want_paused" in d:
            ok = d["paused"] == d["want_paused"]
            return VerificationResult(passed=ok, detail=f"video {'paused' if d['paused'] else 'playing'} in JARVIS browser")
        if d.get("via") == "browser":
            ok = d["url"] != d["before_url"]
            return VerificationResult(passed=ok, detail=f"now on {d['url']}" if ok else "video did not change")
        # Plain media key to another app: Windows gives no simple read-back.
        return VerificationResult(passed=True, detail=f"{a} media key sent x{d.get('times')} (effect not read back)")


class SetVolumeInput(ToolInput):
    level: int = Field(ge=0, le=100)


class SetVolume(Tool):
    name = "set_volume"
    description = "Set the speaker volume to an exact percentage (0-100) and unmute."
    input_model = SetVolumeInput
    timeout_s = 10.0

    async def run(self, args: SetVolumeInput) -> ToolResult:
        audio = _audio(self.ctx)
        await asyncio.to_thread(audio.set_level, args.level)
        if args.level > 0:
            await asyncio.to_thread(audio.set_mute, False)
        level, muted = await asyncio.to_thread(audio.get)
        return ToolResult(ok=True, data={"level": level, "muted": muted, "say": f"Volume {level}%."})

    async def verify(self, args: SetVolumeInput, result: ToolResult) -> VerificationResult:
        ok = abs(result.data["level"] - args.level) <= 1
        return VerificationResult(passed=ok, detail=f"volume is {result.data['level']}%")


# ---------- browser page: scroll, Nth visible video, fullscreen ----------

def _main_page(ctx: Any) -> Any:
    browser = ctx.get("browser")
    page = browser.current_page("main") if browser is not None else None
    if page is None:
        raise ValueError("JARVIS's browser window is not open")
    return page


class ScrollInput(ToolInput):
    direction: Literal["up", "down", "top", "bottom"] = "down"
    times: int = Field(default=1, ge=1, le=20, description="Screens to scroll (up/down)")

    @field_validator("direction", mode="before")
    @classmethod
    def _map(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip().lower()
            return {"upar": "up", "uper": "up", "neeche": "down", "niche": "down", "nichey": "down",
                    "start": "top", "end": "bottom"}.get(v, v)
        return v


def _wheel(clicks: int) -> None:
    import win32api
    import win32con
    win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, clicks * 120, 0)


class ScrollPage(Tool):
    name = "scroll_page"
    description = ("Scroll JARVIS's browser page up/down by screens, or to the top/bottom. Without that window, "
                   "sends mouse-wheel input to the window under the cursor.")
    input_model = ScrollInput
    timeout_s = 10.0

    async def run(self, args: ScrollInput) -> ToolResult:
        try:
            page = _main_page(self.ctx)
        except ValueError:
            clicks = {"up": 5, "down": -5, "top": 50, "bottom": -50}[args.direction] * args.times
            await asyncio.to_thread(self.ctx.get("wheel") or _wheel, clicks)
            return ToolResult(ok=True, data={"via": "mouse_wheel", "clicks": clicks})
        await page.bring_to_front()
        before = await page.evaluate("() => scrollY")
        await page.evaluate(
            "([d, n]) => { const h = innerHeight * 0.85 * n;"
            " if (d === 'top') scrollTo({top: 0});"
            " else if (d === 'bottom') scrollTo({top: document.documentElement.scrollHeight});"
            " else scrollBy({top: d === 'down' ? h : -h}); }",
            [args.direction, args.times])
        await page.wait_for_timeout(400)
        after = await page.evaluate("() => scrollY")
        at_end = await page.evaluate(
            "() => Math.ceil(scrollY + innerHeight) >= document.documentElement.scrollHeight - 2")
        return ToolResult(ok=True, data={"via": "browser", "before": before, "after": after, "at_end": at_end,
                                         "url": page.url})

    async def verify(self, args: ScrollInput, result: ToolResult) -> VerificationResult:
        d = result.data
        if d["via"] == "mouse_wheel":
            return VerificationResult(passed=True, detail="mouse wheel sent to the window under the cursor (not read back)")
        b, a = d["before"], d["after"]
        moved = a > b if args.direction in ("down", "bottom") else a < b
        edge = (args.direction in ("up", "top") and b == 0) or (
            args.direction in ("down", "bottom") and d["at_end"] and a == b)
        detail = f"scrollY {round(b)} -> {round(a)}" + (" (already at the edge)" if edge and not moved else "")
        return VerificationResult(passed=moved or edge, detail=detail)


ORDINALS = {
    "first": 1, "1st": 1, "one": 1, "pehla": 1, "pehli": 1, "pahla": 1, "pahli": 1, "ek": 1,
    "second": 2, "2nd": 2, "two": 2, "dusra": 2, "dusri": 2, "doosra": 2, "doosri": 2,
    "third": 3, "3rd": 3, "three": 3, "teesra": 3, "teesri": 3, "tisra": 3, "tisri": 3, "teen": 3,
    "fourth": 4, "4th": 4, "four": 4, "chautha": 4, "chauthi": 4,
    "fifth": 5, "5th": 5, "five": 5, "panchva": 5, "panchvi": 5, "paanch": 5,
    "sixth": 6, "6th": 6, "six": 6, "seventh": 7, "7th": 7, "eighth": 8, "8th": 8, "last": -1, "aakhri": -1,
}

_VISIBLE_VIDEOS_JS = """() => {
  const cur = new URL(location.href).searchParams.get('v');
  const seen = new Set(), out = [];
  const tileSel = 'ytd-rich-item-renderer, ytd-video-renderer, ytd-compact-video-renderer, ytd-grid-video-renderer, yt-lockup-view-model, ytd-playlist-panel-video-renderer';
  for (const a of document.querySelectorAll('a[href*="/watch?v="]')) {
    const r = a.getBoundingClientRect();
    if (r.width < 40 || r.height < 20 || r.bottom <= 0 || r.top >= innerHeight || r.right <= 0 || r.left >= innerWidth) continue;
    const st = getComputedStyle(a);
    if (st.visibility === 'hidden' || st.display === 'none' || a.offsetParent === null) continue;
    if (a.closest('ytd-ad-slot-renderer, ytd-in-feed-ad-layout-renderer, ytd-promoted-video-renderer')) continue;
    const id = new URL(a.href, location.href).searchParams.get('v');
    if (!id || id === cur || seen.has(id)) continue;
    seen.add(id);
    const tile = a.closest(tileSel);
    const t = tile && tile.querySelector('#video-title, h3, .yt-lockup-metadata-view-model__title');
    out.push({id, href: a.href, top: r.top, left: r.left,
              title: ((t && t.textContent) || a.title || a.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120)});
  }
  out.sort((p, q) => p.top - q.top);
  const rows = [];
  for (const v of out) { const row = rows.find(r => Math.abs(r[0].top - v.top) < 60); row ? row.push(v) : rows.push([v]); }
  return rows.flatMap(r => r.sort((p, q) => p.left - q.left));
}"""


class PlayVisibleVideoInput(ToolInput):
    position: int = Field(ge=-1, le=30, description="1 = first video visible on screen, 2 = second..., -1 = last")

    @field_validator("position", mode="before")
    @classmethod
    def _map(cls, v: Any) -> Any:
        if isinstance(v, str) and v.strip().lower() in ORDINALS:
            return ORDINALS[v.strip().lower()]
        return v

    @field_validator("position")
    @classmethod
    def _nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("position starts at 1")
        return v


class PlayVisibleVideo(Tool):
    name = "play_visible_video"
    description = ("On the YouTube page in JARVIS's browser, play the Nth video currently visible on screen "
                   "(left to right, top to bottom; the playing video itself is skipped).")
    input_model = PlayVisibleVideoInput

    async def run(self, args: PlayVisibleVideoInput) -> ToolResult:
        page = _main_page(self.ctx)
        if host_of(page.url) not in ("youtube.com", "m.youtube.com"):
            return ToolResult(ok=False, error=f"the browser is on {host_of(page.url) or 'a blank page'}, not YouTube")
        await page.bring_to_front()
        videos = await page.evaluate(_VISIBLE_VIDEOS_JS)
        if not videos:
            try:  # thumbnails may still be rendering
                await page.wait_for_selector('a[href*="/watch?v="]', timeout=8000)
            except Exception:
                pass
            videos = await page.evaluate(_VISIBLE_VIDEOS_JS)
        n = args.position
        if not videos or n > len(videos):
            return ToolResult(ok=False, error=f"only {len(videos)} videos are visible on screen")
        pick = videos[n - 1 if n > 0 else -1]
        await page.goto(pick["href"], wait_until="domcontentloaded")
        try:
            await page.wait_for_selector("video", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)
        paused = await page.evaluate(_PAUSED_JS)
        return ToolResult(ok=True, data={"picked": pick, "visible": len(videos), "url": page.url,
                                         "has_video": paused is not None, "paused": paused})

    async def verify(self, args: PlayVisibleVideoInput, result: ToolResult) -> VerificationResult:
        from urllib.parse import parse_qs
        d = result.data
        vid = parse_qs(urlparse(d["url"]).query).get("v", [""])[0]
        if vid != d["picked"]["id"] or not d["has_video"]:
            return VerificationResult(passed=False, detail=f"expected video {d['picked']['id']}, page is {d['url']}")
        note = " (paused by autoplay policy; press play)" if d.get("paused") else ""
        return VerificationResult(passed=True, detail=f"playing #{args.position} of {d['visible']} visible: "
                                                      f"{d['picked']['title'] or vid}{note}")


class FullscreenInput(ToolInput):
    mode: Literal["enter", "exit"] = "enter"

    @field_validator("mode", mode="before")
    @classmethod
    def _map(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = re.sub(r"\s+", " ", v.strip().lower())
            if v in ("exit", "leave", "close", "turn off", "off", "band karo", "band", "hatao", "chhota karo",
                     "minimize", "escape"):
                return "exit"
            if v in ("enter", "on", "open", "go", "make", "karo"):
                return "enter"
        return v


_FS_JS = "() => !!document.fullscreenElement"


class VideoFullscreen(Tool):
    name = "video_fullscreen"
    description = "Enter or exit fullscreen for the YouTube video in JARVIS's browser."
    input_model = FullscreenInput
    timeout_s = 15.0

    async def run(self, args: FullscreenInput) -> ToolResult:
        page = _main_page(self.ctx)
        if "youtube.com/watch" not in page.url:
            return ToolResult(ok=False, error="no YouTube video is open in JARVIS's browser")
        await page.bring_to_front()
        want = args.mode == "enter"
        if await page.evaluate(_FS_JS) != want:
            # A real (trusted) key press: requestFullscreen() from script is blocked without a user gesture.
            await page.evaluate("() => document.activeElement && document.activeElement.blur()")
            await page.locator("video").first.hover()
            await page.keyboard.press("f")
            for _ in range(12):
                await page.wait_for_timeout(250)
                if await page.evaluate(_FS_JS) == want:
                    break
        return ToolResult(ok=True, data={"fullscreen": await page.evaluate(_FS_JS)})

    async def verify(self, args: FullscreenInput, result: ToolResult) -> VerificationResult:
        fs = result.data["fullscreen"]
        return VerificationResult(passed=fs == (args.mode == "enter"), detail=f"fullscreen is {'on' if fs else 'off'}")


# ---------- YouTube ad skip ----------

_AD_JS = "() => !!document.querySelector('.html5-video-player.ad-showing')"
# YouTube has renamed this button several times; try every known class.
SKIP_AD_BUTTONS = ".ytp-skip-ad-button, .ytp-ad-skip-button-modern, .ytp-ad-skip-button, .ytp-ad-skip-button-slot button"


class SkipAdInput(ToolInput):
    wait_s: int = Field(default=8, ge=0, le=15, description="Seconds to wait for the Skip button to appear")


class SkipAd(Tool):
    name = "skip_ad"
    description = ("Skip the ad on the YouTube video in JARVIS's browser: clicks YouTube's Skip button, waiting up "
                   "to wait_s seconds for it to appear. Unskippable ads cannot be skipped. Not the same as "
                   "media_key next (that changes the video).")
    input_model = SkipAdInput
    timeout_s = 30.0

    async def run(self, args: SkipAdInput) -> ToolResult:
        page = _main_page(self.ctx)
        if "youtube.com/watch" not in page.url:
            return ToolResult(ok=False, error="no YouTube video is open in JARVIS's browser")
        if not await page.evaluate(_AD_JS):
            return ToolResult(ok=True, data={"ad": False, "skipped": False, "say": "No ad is playing."})
        buttons = page.locator(SKIP_AD_BUTTONS)
        clicked = False
        for _ in range(args.wait_s * 4 + 1):
            if not await page.evaluate(_AD_JS):  # ad ended on its own while waiting
                break
            n = await buttons.count()
            for i in range(n):
                b = buttons.nth(i)
                if await b.is_visible():
                    await b.click()  # a real click; a script click() is ignored by the player
                    clicked = True
                    break
            if clicked:
                break
            await page.wait_for_timeout(250)
        ad_now = True
        for _ in range(12):
            ad_now = await page.evaluate(_AD_JS)
            if not ad_now or not clicked:
                break
            await page.wait_for_timeout(250)
        say = ("Ad skipped." if clicked and not ad_now else "Ad finished." if not ad_now
               else "Skipped one ad, another ad is playing." if clicked else "This ad can't be skipped yet.")
        return ToolResult(ok=True, data={"ad": True, "clicked": clicked, "ad_showing": ad_now, "say": say})

    async def verify(self, args: SkipAdInput, result: ToolResult) -> VerificationResult:
        d = result.data
        if not d["ad"]:
            return VerificationResult(passed=True, detail="no ad was playing")
        if not d["ad_showing"]:
            return VerificationResult(passed=True, detail="ad skipped" if d["clicked"] else "ad ended while waiting")
        if d["clicked"]:  # a second ad in the same break started; the first one was skipped
            return VerificationResult(passed=True, detail="skipped one ad; another ad is playing")
        return VerificationResult(passed=False, detail=f"no Skip button within {args.wait_s}s (unskippable ad?)")


# ---------- display rotation ----------

ORIENTATIONS = {"landscape": 0, "portrait": 1, "landscape_flipped": 2, "portrait_flipped": 3}
ORIENTATION_SYNONYMS = {
    "0": "landscape", "back": "landscape", "normal": "landscape", "reset": "landscape", "undo": "landscape",
    "fix": "landscape", "seedha": "landscape", "sidha": "landscape", "default": "landscape",
    "90": "portrait", "rotate": "portrait", "ghumao": "portrait", "right": "portrait",
    "180": "landscape_flipped", "upside down": "landscape_flipped", "ulta": "landscape_flipped",
    "270": "portrait_flipped", "left": "portrait_flipped",
}


class RotateScreenInput(ToolInput):
    orientation: Literal["landscape", "portrait", "landscape_flipped", "portrait_flipped"] = "portrait"

    @field_validator("orientation", mode="before")
    @classmethod
    def _map(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = re.sub(r"\s+", " ", v.strip().lower())
            return ORIENTATION_SYNONYMS.get(v, v.replace(" ", "_"))
        return v


class Display:
    """Primary display orientation via ChangeDisplaySettingsEx (no admin needed)."""

    def get(self) -> int:
        import win32api
        import win32con
        return win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS).DisplayOrientation

    def set(self, orientation: int) -> int:
        import win32api
        import win32con
        dm = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
        if dm.DisplayOrientation % 2 != orientation % 2:
            dm.PelsWidth, dm.PelsHeight = dm.PelsHeight, dm.PelsWidth
        dm.DisplayOrientation = orientation
        dm.Fields |= 0x80 | win32con.DM_PELSWIDTH | win32con.DM_PELSHEIGHT  # 0x80 = DM_DISPLAYORIENTATION
        return win32api.ChangeDisplaySettingsEx(None, dm, 0)


class RotateScreen(Tool):
    name = "rotate_screen"
    description = ("Rotate the primary display: landscape (normal), portrait, landscape_flipped, portrait_flipped. "
                   "Changes a system setting, so it always asks for approval.")
    input_model = RotateScreenInput
    requires_approval = True
    timeout_s = 15.0

    def describe_approval(self, args: RotateScreenInput) -> str:
        return (f"Change the primary display orientation to {args.orientation.replace('_', ' ')} (Windows display "
                "setting). Undo any time with: rotate screen back")

    async def run(self, args: RotateScreenInput) -> ToolResult:
        disp = self.ctx.get("display") or Display()
        before = await asyncio.to_thread(disp.get)
        target = ORIENTATIONS[args.orientation]
        code = 0 if before == target else await asyncio.to_thread(disp.set, target)
        if code != 0:
            return ToolResult(ok=False, error=f"Windows refused the rotation (ChangeDisplaySettingsEx returned "
                                              f"{code}); the display driver may not support it")
        await asyncio.sleep(0.5)
        return ToolResult(ok=True, data={"before": before, "after": await asyncio.to_thread(disp.get)})

    async def verify(self, args: RotateScreenInput, result: ToolResult) -> VerificationResult:
        names = {v: k for k, v in ORIENTATIONS.items()}
        after = result.data["after"]
        return VerificationResult(passed=after == ORIENTATIONS[args.orientation],
                                  detail=f"display is {names.get(after, after)}")


# ---------- timers ----------

UNIT_SECONDS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "m": 60, "min": 60, "mins": 60,
                "minute": 60, "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600, "ghante": 3600, "ghanta": 3600}


class SetTimerInput(ToolInput):
    amount: int = Field(ge=1, le=1440)
    unit: str = "minutes"
    label: str = Field(default="", max_length=120)

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in UNIT_SECONDS:
            raise ValueError(f"unknown unit {v!r}")
        return v


def _span(seconds: int) -> str:
    parts = [(seconds // 3600, "hour"), (seconds % 3600 // 60, "minute"), (seconds % 60, "second")]
    return " ".join(f"{n} {u}{'s' if n != 1 else ''}" for n, u in parts if n) or "0 seconds"


class SetTimer(Tool):
    name = "set_timer"
    description = ("Start a countdown; when it ends JARVIS speaks the label and shows a notification. "
                   "Timers live in the backend process and are lost if JARVIS restarts.")
    input_model = SetTimerInput
    timeout_s = 5.0

    async def run(self, args: SetTimerInput) -> ToolResult:
        seconds = args.amount * UNIT_SECONDS[args.unit]
        if seconds > 24 * 3600:
            return ToolResult(ok=False, error="timers are limited to 24 hours")
        due = datetime.now() + timedelta(seconds=seconds)
        timers: set[asyncio.Task] = self.ctx.get("timers") or set()
        self.ctx.timers = timers
        task = asyncio.get_running_loop().create_task(self._ring(seconds, args.label, due))
        timers.add(task)
        task.add_done_callback(timers.discard)
        what = f" for {args.label}" if args.label else ""
        return ToolResult(ok=True, data={"due": due.isoformat(timespec="seconds"), "seconds": seconds,
                                         "say": f"Timer set{what}: {_span(seconds)}, "
                                                f"until {due.strftime('%I:%M %p').lstrip('0')}."})

    async def _ring(self, seconds: int, label: str, due: datetime) -> None:
        await asyncio.sleep(seconds)
        text = f"Time's up{': ' + label if label else ''}."
        bus = self.ctx.get("bus")
        if bus is not None:
            bus.emit("timer_done", label=label, due=due.isoformat(timespec="seconds"), message=text)
        tts = self.ctx.get("tts")
        if tts is not None:
            try:
                await tts.speak(text)
            except Exception:
                pass

    async def verify(self, args: SetTimerInput, result: ToolResult) -> VerificationResult:
        timers = self.ctx.get("timers") or set()
        alive = any(not t.done() for t in timers)
        return VerificationResult(passed=alive, detail=result.data.get("say", "") if alive else "timer not scheduled")


# ---------- screenshot ----------

class ScreenshotInput(ToolInput):
    pass


def _grab(path: Path) -> None:
    from PIL import ImageGrab
    ImageGrab.grab(all_screens=True).save(path)


class TakeScreenshot(Tool):
    name = "take_screenshot"
    description = "Save a screenshot of all monitors as a PNG under JARVIS's data\\screenshots folder."
    input_model = ScreenshotInput
    timeout_s = 15.0

    async def run(self, args: ScreenshotInput) -> ToolResult:
        out_dir = Path(self.ctx.settings.data_dir) / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"screenshot-{datetime.now():%Y%m%d-%H%M%S}.png"

        await asyncio.to_thread(self.ctx.get("screen_grabber") or _grab, path)
        return ToolResult(ok=True, data={"path": str(path), "say": f"Screenshot saved as {path.name}."})

    async def verify(self, args: ScreenshotInput, result: ToolResult) -> VerificationResult:
        p = Path(result.data.get("path", ""))
        ok = p.is_file() and p.stat().st_size > 0
        return VerificationResult(passed=ok, detail=str(p) if ok else "screenshot file missing")
