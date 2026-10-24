"""Everyday commands must route locally (zero planner calls) to the right workflow with the right args."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from jarvis.registry.seed_workflows import SEEDS
from jarvis.tools.base import ToolContext
from jarvis.tools.daily import (APP_SYNONYMS, APPS, SITE_SYNONYMS, SITES, FullscreenInput, MediaKey, MediaKeyInput,
                                OpenApp, OpenAppInput, OpenSiteInput, PlayVisibleVideoInput, RotateScreen,
                                RotateScreenInput, ScreenshotInput, ScrollInput, ScrollPage, SetTimer, SetTimerInput,
                                SetVolume, SetVolumeInput, TakeScreenshot, TellTimeInput, VideoFullscreen,
                                describe_now, resolve_app, resolve_site, search_url)

from .conftest import plan_json

# (command, workflow, expected step args or None to skip the args check)
CASES = [
    # web search / questions
    ("google best laptops under 50000", "web_search", {"query": "best laptops under 50000"}),
    ("Search for C++ tutorials", "web_search", {"query": "C++ tutorials"}),
    ("look up the capital of australia", "web_search", {"query": "the capital of australia"}),
    ("What is quantum computing?", "web_search", {"query": "What is quantum computing"}),
    ("who is the prime minister of india", "web_search", {"query": "who is the prime minister of india"}),
    ("how to make pancakes", "web_search", {"query": "how to make pancakes"}),
    ("define serendipity", "web_search", {"query": "define serendipity"}),
    ("what time is it in london", "web_search", {"query": "what time is it in london"}),
    ("google pe ipl score search karo", "web_search", {"query": "ipl score"}),
    ("python decorators google karo", "web_search", {"query": "python decorators"}),
    ("machine learning kya hai", "web_search", {"query": "machine learning kya hai"}),
    # weather
    ("what's the weather", "weather", {"query": "weather "}),
    ("weather in Mumbai", "weather", {"query": "weather Mumbai"}),
    ("how is the weather in delhi today", "weather", {"query": "weather delhi"}),
    ("will it rain today", "weather", None),
    ("aaj ka mausam kaisa hai", "weather", None),
    ("patna ka mausam", "weather", {"query": "weather patna"}),
    # time and date
    ("what time is it", "tell_time", {"what": "time"}),
    ("Jarvis, what's the time?", "tell_time", {"what": "time"}),
    ("what is the date today", "tell_time", {"what": "date"}),
    ("what day is it", "tell_time", {"what": "day"}),
    ("time kya hua", "tell_time", {}),
    ("kitne baje hai", "tell_time", {}),
    ("aaj kya date hai", "tell_time", {"what": "date"}),
    # websites
    ("open gmail", "open_site", {"site": "gmail"}),
    ("check my email", "open_site", {"site": "email"}),
    ("open youtube", "open_site", {"site": "youtube"}),
    ("go to github", "open_site", {"site": "github"}),
    ("open whatsapp web", "open_site", {"site": "whatsapp web"}),
    ("Open ChatGPT", "open_site", {"site": "ChatGPT"}),
    ("open google drive", "open_site", {"site": "google drive"}),
    ("show my calendar", "open_site", {"site": "calendar"}),
    ("open linkedin", "open_site", {"site": "linkedin"}),
    ("open netflix", "open_site", {"site": "netflix"}),
    ("visit wikipedia.org", "open_site", {"site": "wikipedia.org"}),
    ("open https://example.com/docs", "open_site", {"site": "https://example.com/docs"}),
    ("instagram kholo", "open_site", {"site": "instagram"}),
    # apps and folders
    ("open notepad", "open_app", {"app": "notepad"}),
    ("launch calculator", "open_app", {"app": "calculator"}),
    ("open calc", "open_app", {"app": "calc"}),
    ("open file explorer", "open_app", {"app": "file explorer"}),
    ("open settings", "open_app", {"app": "settings"}),
    ("open my downloads", "open_app", {"app": "downloads"}),
    ("open documents folder", "open_app", {"app": "documents folder"}),
    ("open vs code", "open_app", {"app": "vs code"}),
    ("start microsoft word", "open_app", {"app": "microsoft word"}),
    ("open chrome", "open_app", {"app": "chrome"}),
    ("notepad kholo", "open_app", {"app": "notepad"}),
    # media and volume
    ("pause", "media_control", {"action": "pause"}),
    ("pause the music", "media_control", {"action": "pause"}),
    ("resume", "media_control", {"action": "resume"}),
    ("play music", "media_control", {"action": "play"}),
    ("next song", "media_control", {"action": "next"}),
    ("skip", "media_control", {"action": "skip"}),
    ("play the previous track", "media_control", {"action": "previous"}),
    ("volume up", "media_control", {"action": "volume up"}),
    ("turn down the volume", "media_control", {"action": "turn down"}),
    ("mute", "media_control", {"action": "mute"}),
    ("awaaz badhao", "media_control", {"action": "badhao"}),
    ("gaana roko", "media_control", {"action": "roko"}),
    ("agla gaana", "media_control", {"action": "agla"}),
    ("video pause karo", "media_control", {"action": "pause karo"}),
    ("youtube play karo", "media_control", {"action": "play karo"}),
    ("pause kar do", "media_control", {"action": "pause kar do"}),
    ("gaana wapas chalao", "media_control", {"action": "wapas chalao"}),
    ("pause the youtube video", "media_control", {"action": "pause"}),
    # youtube ads
    ("skip ad", "skip_ad", {}),
    ("skip the ad", "skip_ad", {}),
    ("skip ads", "skip_ad", {}),
    ("skip this advertisement", "skip_ad", {}),
    ("ad skip karo", "skip_ad", {}),
    ("ad skip kar do", "skip_ad", {}),
    ("add skip karo", "skip_ad", {}),
    ("ad hatao", "skip_ad", {}),
    ("volume 50", "set_volume", {"level": "50"}),
    ("set volume to 30%", "set_volume", {"level": "30"}),
    ("volume 20 karo", "set_volume", {"level": "20"}),
    ("unmute", "media_control", {"action": "unmute"}),
    # scrolling
    ("scroll down", "scroll_page", {"direction": "down"}),
    ("scroll up a bit", "scroll_page", {"direction": "up"}),
    ("scroll down 3 times", "scroll_page", {"direction": "down", "times": "3"}),
    ("go to the top", "scroll_page", {"direction": "top"}),
    ("page down", "scroll_page", {"direction": "down"}),
    ("neeche scroll karo", "scroll_page", {"direction": "neeche"}),
    ("upar karo", "scroll_page", {"direction": "upar"}),
    # Nth video visible on screen
    ("play the second video", "play_visible_video", {"position": "second"}),
    ("play 1st video", "play_visible_video", {"position": "1st"}),
    ("open the third result", "play_visible_video", {"position": "third"}),
    ("video number 4", "play_visible_video", {"position": "4"}),
    ("dusra video chalao", "play_visible_video", {"position": "dusra"}),
    ("screen pe dikh rahe pehla video chalao", "play_visible_video", {"position": "pehla"}),
    ("2nd wala video play karo", "play_visible_video", {"position": "2nd"}),
    # fullscreen
    ("full screen", "video_fullscreen", {}),
    ("make it fullscreen", "video_fullscreen", {}),
    ("fullscreen karo", "video_fullscreen", {}),
    ("exit full screen", "video_fullscreen", {"mode": "exit"}),
    ("full screen band karo", "video_fullscreen", {"mode": "band karo"}),
    # screen rotation
    ("rotate screen", "rotate_screen", {}),
    ("rotate the screen 180", "rotate_screen", {"orientation": "180"}),
    ("rotate screen back", "rotate_screen", {"orientation": "back"}),
    ("portrait mode", "rotate_screen", {"orientation": "portrait"}),
    ("reset screen rotation", "rotate_screen", {"orientation": "reset"}),
    ("screen seedha karo", "rotate_screen", {"orientation": "seedha"}),
    # camera
    ("open camera", "open_app", {"app": "camera"}),
    ("turn on the camera", "open_app", {"app": "camera"}),
    ("camera on karo", "open_app", {"app": "camera"}),
    ("webcam on", "open_app", {"app": "webcam"}),
    # youtube
    ("play a video about python decorators", "youtube_play", {"query": "python decorators"}),
    ("play arijit singh songs", "youtube_play", {"query": "arijit singh"}),
    ("play lofi beats on youtube", "youtube_play", {"query": "lofi beats"}),
    ("search mr beast on youtube", "youtube_play", {"query": "mr beast"}),
    ("youtube pe lofi chalao", "youtube_play", {"query": "lofi"}),
    ("kesariya song bajao", "youtube_play", {"query": "kesariya song"}),
    # timers and reminders
    ("set a timer for 5 minutes", "set_timer", {"amount": "5", "unit": "minutes"}),
    ("10 minute timer", "set_timer", {"amount": "10", "unit": "minute"}),
    ("timer 30 sec", "set_timer", {"amount": "30", "unit": "sec"}),
    ("remind me in 20 minutes to drink water", "set_timer", {"amount": "20", "unit": "minutes", "label": "drink water"}),
    ("remind me to call mom in 1 hour", "set_timer", {"amount": "1", "unit": "hour", "label": "call mom"}),
    ("5 minute ka timer laga do", "set_timer", {"amount": "5", "unit": "minute"}),
    # screenshot
    ("take a screenshot", "take_screenshot", {}),
    ("screenshot", "take_screenshot", {}),
    ("capture my screen", "take_screenshot", {}),
    # maps
    ("directions to india gate", "directions", {"query": "india gate", "engine": "directions"}),
    ("how do i get to connaught place", "directions", {"query": "connaught place", "engine": "directions"}),
    ("restaurants near me", "maps_search", {"query": "restaurants near me", "engine": "maps"}),
    ("where is the nearest petrol pump", "maps_search", {"query": "nearest petrol pump", "engine": "maps"}),
    ("show taj mahal on map", "maps_search", {"query": "taj mahal", "engine": "maps"}),
    # store / dev searches
    ("search headphones on amazon", "site_search", {"query": "headphones", "engine": "amazon"}),
    ("iphone 16 on flipkart", "site_search", {"query": "iphone 16", "engine": "flipkart"}),
    ("wikipedia albert einstein", "site_search", {"query": "albert einstein", "engine": "wikipedia"}),
    ("search fastapi on github", "site_search", {"query": "fastapi", "engine": "github"}),
    # existing seeds still win
    ("open my coding workspace for two-sum", "coding_workspace", None),
    ("meeting notes titled Standup notes all good", "notion_meeting_notes", None),
]

# Must NOT be grabbed by an everyday pattern (they need the planner, or a question to the user).
PLANNER_CASES = [
    "open notepad and type hello",
    "open example dot com in my browser",
    "order a pizza from dominos",
    "delete everything",
    "send an email to my boss",
]


@pytest.mark.parametrize("text,workflow,args", CASES, ids=[c[0] for c in CASES])
async def test_everyday_command_routes_locally(make_jarvis, text, workflow, args):
    j = make_jarvis(responder=lambda s, u: pytest.fail(f"planner called for {text!r}"))
    d = j.router.route_local(text)
    assert d is not None, f"{text!r} missed local routing"
    assert d.kind == "run", (text, d.kind, d.message)
    assert d.workflow.name == workflow, (text, d.workflow.name, d.via)
    if args is not None:
        assert d.steps[0]["args"] == args, (text, d.steps[0]["args"])
    for s in d.steps:  # every step's args must validate against the real tool input model
        j.registry.validate(s["tool"], s["args"])
    assert j.provider.calls == []


@pytest.mark.parametrize("text", PLANNER_CASES)
def test_not_grabbed_by_everyday_patterns(make_jarvis, text):
    j = make_jarvis()
    d = j.router.route_local(text)
    assert d is None or d.kind == "confirm", (text, d and d.workflow and d.workflow.name)


async def test_everyday_runs_end_to_end_with_zero_planner_calls(make_jarvis):
    j = make_jarvis(responder=lambda s, u: plan_json())
    for text in ("open gmail", "what time is it", "volume up", "google weather in delhi", "take a screenshot"):
        r = await j.handle_command(text)
        assert r["route"] == "local" and r["status"] == "succeeded", (text, r)
    assert j.provider.calls == []
    assert j.db.usage_summary()["planner_calls"] == 0


def test_seed_patterns_compile_and_names_unique():
    names = [s["name"] for s in SEEDS]
    assert len(names) == len(set(names))
    for s in SEEDS:
        for p in s["patterns"]:
            re.compile(p)


def test_site_and_app_names_do_not_overlap():
    sites = set(SITES) | set(SITE_SYNONYMS)
    apps = set(APPS) | set(APP_SYNONYMS)
    assert not sites & apps


def test_seed_update_bumps_version_and_replaces_patterns(make_jarvis):
    from jarvis.registry.seed_workflows import seed
    j = make_jarvis()
    wf = j.db.get_workflow_by_name("tell_time")
    j.db.save_workflow(name="tell_time", steps=wf.steps, params_schema=wf.params_schema, aliases=wf.aliases,
                       patterns=["^stale$"], canonical_intent=wf.canonical_intent, replace_patterns=True)
    seed(j.db)
    new = j.db.get_workflow_by_name("tell_time")
    assert new.version == wf.version + 2 and "^stale$" not in new.patterns
    seed(j.db)  # unchanged -> no new version
    assert j.db.get_workflow_by_name("tell_time").version == new.version


# ---------- daily tools ----------

def test_resolve_site_and_search_urls():
    assert resolve_site("Mail") == "https://mail.google.com"
    assert resolve_site("example.com") == "https://example.com"
    assert resolve_site("https://a.b/c?d=1") == "https://a.b/c?d=1"
    with pytest.raises(ValueError):
        resolve_site("not a site at all")
    with pytest.raises(ValidationError):
        OpenSiteInput(site="file:///C:/Windows")
    assert search_url("google", "c++ & rust") == "https://www.google.com/search?q=c%2B%2B+%26+rust"
    assert search_url("maps", "india gate") == "https://www.google.com/maps/search/india%20gate"


def test_resolve_app_allowlist():
    assert resolve_app("Calc")[1] == "calc.exe"
    assert resolve_app("my downloads")[1] == str(Path.home() / "Downloads")
    with pytest.raises(ValidationError):
        OpenAppInput(app="cmd.exe /c del *")


async def test_open_app_launches_allowlisted_target_and_verifies_window():
    launched = []

    class W:
        def list_windows(self):
            return [{"hwnd": 5, "title": "Untitled - Notepad", "class": "Notepad"}]

    ctx = ToolContext(launcher=launched.append, win32=W())
    tool = OpenApp(ctx)
    args = OpenAppInput(app="notepad")
    r = await tool.run(args)
    assert launched == ["notepad.exe"] and (await tool.verify(args, r)).passed


async def test_open_app_reports_not_installed():
    def boom(_):
        raise FileNotFoundError("The system cannot find the file specified")
    r = await OpenApp(ToolContext(launcher=boom)).run(OpenAppInput(app="excel"))
    assert not r.ok and "installed" in r.error


def test_tell_time_text():
    now = datetime(2026, 10, 21, 15, 4)
    assert describe_now("time", now) == "It's 3:04 PM."
    assert describe_now("date", now) == "Today is Wednesday, 21 October 2026."
    assert TellTimeInput(what="din").what == "date"


class FakeAudio:
    def __init__(self, level=50, muted=False):
        self.level, self.muted = level, muted

    def get(self):
        return self.level, self.muted

    def set_level(self, pct):
        self.level = max(0, min(100, pct))

    def set_mute(self, m):
        self.muted = m


async def test_volume_is_changed_and_read_back():
    audio = FakeAudio(50, muted=True)
    tool = MediaKey(ToolContext(audio=audio))
    for action, want in (("Turn Up", (60, False)), ("kam karo", (50, False)), ("mute", (50, True)),
                         ("unmute", (50, False))):
        args = MediaKeyInput(action=action)
        r = await tool.run(args)
        assert audio.get() == want and (await tool.verify(args, r)).passed, action
    audio.level = 100
    args = MediaKeyInput(action="volume up")
    assert (await tool.verify(args, await tool.run(args))).passed  # already at max


async def test_volume_verification_fails_if_windows_ignores_it():
    class Stuck(FakeAudio):
        def set_level(self, pct):
            pass
    tool = MediaKey(ToolContext(audio=Stuck(40)))
    args = MediaKeyInput(action="volume_up")
    v = await tool.verify(args, await tool.run(args))
    assert not v.passed and "40% -> 40%" in v.detail


async def test_set_volume_exact():
    audio = FakeAudio(10, muted=True)
    tool = SetVolume(ToolContext(audio=audio))
    args = SetVolumeInput(level="35")
    r = await tool.run(args)
    assert audio.get() == (35, False) and (await tool.verify(args, r)).passed
    with pytest.raises(ValidationError):
        SetVolumeInput(level=150)


async def test_media_keys_without_jarvis_browser():
    pressed = []
    tool = MediaKey(ToolContext(key_presser=lambda vk, n: pressed.append((vk, n))))
    for action in ("pause", "agla", "pichla"):
        await tool.run(MediaKeyInput(action=action))
    assert pressed == [(0xB3, 1), (0xB0, 1), (0xB1, 1)]
    with pytest.raises(ValidationError):
        MediaKeyInput(action="format c drive")


class FakePage:
    """Just enough of a Playwright page for the browser tools."""

    def __init__(self, url="https://www.youtube.com/watch?v=abc", paused=False):
        self.url, self.scroll, self.height, self.paused, self.fs = url, 0, 5000, paused, False
        self.keys = []

    async def bring_to_front(self):
        pass

    async def wait_for_timeout(self, ms):
        pass

    async def evaluate(self, js, arg=None):
        if js == "() => scrollY":
            return self.scroll
        if "scrollBy" in js:
            d, n = arg
            nxt = {"top": 0, "bottom": self.height}.get(d, self.scroll + (680 * n if d == "down" else -680 * n))
            self.scroll = max(0, min(nxt, self.height - 800))
            return None
        if "scrollHeight - 2" in js:
            return self.scroll >= self.height - 800
        if "!!document.querySelector('video')" in js:
            return True
        if "v.pause()" in js:
            self.paused = arg
            return None
        if "v.paused" in js:
            return self.paused
        if "fullscreenElement" in js:
            return self.fs
        return None

    def locator(self, sel):
        class L:
            async def hover(self):
                pass
        loc = L()
        loc.first = loc
        return loc

    @property
    def keyboard(self):
        page = self

        class K:
            async def press(self, k):
                page.keys.append(k)
                if k == "f":
                    page.fs = not page.fs
        return K()


class FakeBrowser:
    def __init__(self, page):
        self.page_ = page

    def current_page(self, window):
        return self.page_


async def test_scroll_page_reads_back_position():
    page = FakePage(url="https://www.google.com/search?q=x")
    tool = ScrollPage(ToolContext(browser=FakeBrowser(page)))
    for direction, want in (("down", 680), ("neeche", 1360), ("upar", 680), ("top", 0), ("up", 0)):
        args = ScrollInput(direction=direction)
        v = await tool.verify(args, await tool.run(args))
        assert page.scroll == want and v.passed, (direction, v.detail)


async def test_scroll_without_browser_uses_mouse_wheel():
    clicks = []
    tool = ScrollPage(ToolContext(wheel=clicks.append))
    r = await tool.run(ScrollInput(direction="down", times=2))
    assert clicks == [-10] and r.data["via"] == "mouse_wheel"


async def test_pause_and_play_control_the_jarvis_video():
    page = FakePage(paused=False)
    tool = MediaKey(ToolContext(browser=FakeBrowser(page), key_presser=lambda *a: pytest.fail("key sent")))
    for action, paused in (("pause", True), ("resume", False), ("play pause", True)):
        args = MediaKeyInput(action=action)
        v = await tool.verify(args, await tool.run(args))
        assert page.paused is paused and v.passed, action


async def test_fullscreen_toggles_with_trusted_key():
    page = FakePage()
    tool = VideoFullscreen(ToolContext(browser=FakeBrowser(page)))
    for mode, fs in (("enter", True), ("enter", True), ("band karo", False)):
        args = FullscreenInput(mode=mode)
        v = await tool.verify(args, await tool.run(args))
        assert page.fs is fs and v.passed, mode
    assert page.keys == ["f", "f"]  # no extra press when already in the wanted state
    r = await VideoFullscreen(ToolContext(browser=FakeBrowser(FakePage(url="https://github.com")))).run(FullscreenInput())
    assert not r.ok


def test_visible_video_position_words():
    assert PlayVisibleVideoInput(position="dusra").position == 2
    assert PlayVisibleVideoInput(position="3rd").position == 3
    assert PlayVisibleVideoInput(position="last").position == -1
    with pytest.raises(ValidationError):
        PlayVisibleVideoInput(position="0")


async def test_rotate_screen_reads_back():
    class FakeDisplay:
        o = 0

        def get(self):
            return self.o

        def set(self, o):
            self.o = o
            return 0
    disp = FakeDisplay()
    tool = RotateScreen(ToolContext(display=disp))
    assert tool.requires_approval
    for words, o in (("portrait", 1), ("upside down", 2), ("back", 0)):
        args = RotateScreenInput(orientation=words)
        assert (await tool.verify(args, await tool.run(args))).passed and disp.o == o


async def test_rotate_screen_reports_driver_refusal():
    class Refuses:
        def get(self):
            return 0

        def set(self, o):
            return -2
    r = await RotateScreen(ToolContext(display=Refuses())).run(RotateScreenInput())
    assert not r.ok and "-2" in r.error


async def test_rotate_waits_for_approval_in_a_run(make_jarvis):
    j = make_jarvis()
    r = await j.handle_command("rotate screen")
    assert r["status"] == "cancelled" and j.fakes["rotate_screen"].calls == []  # approval timed out


def test_installed_apps_route_and_resolve(make_jarvis):
    from jarvis.registry.seed_workflows import seed
    from jarvis.tools import daily
    try:
        daily.set_installed_apps({"Spotify": "SpotifyAB.Spotify!Spotify", "Android Studio": r"{X}\studio64.exe",
                                  "Uninstall Foo": "foo", "WhatsApp": "WA!App"})
        j = make_jarvis()
        seed(j.db)
        for text, app in (("open android studio", "android studio"), ("launch Spotify app", "Spotify"),
                          ("android studio kholo", "android studio"), ("open whatsapp app", "whatsapp")):
            d = j.router.route_local(text)
            assert d and d.workflow.name == "open_app" and d.steps[0]["args"] == {"app": app}, text
        assert j.router.route_local("open whatsapp").workflow.name == "open_site"  # the site wins without "app"
        assert daily.resolve_app("android studio")[1] == r"shell:AppsFolder\{X}\studio64.exe"
        assert daily.resolve_app("andriod studio")[0] == "android studio"  # typo, fuzzy match
        with pytest.raises(ValueError):
            daily.resolve_app("uninstall foo")
    finally:
        daily.set_installed_apps({})


async def test_installed_app_verified_by_new_window():
    from jarvis.tools import daily

    class W:
        def __init__(self):
            self.wins = [{"hwnd": 1, "title": "Dashboard"}]

        def list_windows(self):
            return list(self.wins)

    w = W()
    daily.set_installed_apps({"Foo Bar Pro": "foo!app"})
    try:
        tool = OpenApp(ToolContext(launcher=lambda t: w.wins.append({"hwnd": 2, "title": "Welcome"}), win32=w))
        args = OpenAppInput(app="foo bar pro")
        v = await tool.verify(args, await tool.run(args))
        assert v.passed and "Welcome" in v.detail
    finally:
        daily.set_installed_apps({})


async def test_set_timer_fires_and_announces():
    events = []

    class Bus:
        def emit(self, t, **d):
            events.append((t, d))

    ctx = ToolContext(bus=Bus())
    tool = SetTimer(ctx)
    args = SetTimerInput(amount="1", unit="sec", label="tea")
    r = await tool.run(args)
    assert r.ok and "1 second" in r.data["say"] and (await tool.verify(args, r)).passed
    import asyncio
    await asyncio.sleep(1.3)
    assert events and events[0][0] == "timer_done" and "tea" in events[0][1]["message"]
    with pytest.raises(ValidationError):
        SetTimerInput(amount=5, unit="fortnights")


async def test_screenshot_saves_under_data_dir(settings):
    def fake_grab(path):
        Path(path).write_bytes(b"png")
    tool = TakeScreenshot(ToolContext(settings=settings, screen_grabber=fake_grab))
    r = await tool.run(ScreenshotInput())
    assert Path(r.data["path"]).parent == settings.data_dir / "screenshots"
    assert (await tool.verify(ScreenshotInput(), r)).passed
