"""Voice choice with fallback, preferences, wake phrase matching and segmentation (no real audio)."""
from __future__ import annotations

import asyncio
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from jarvis.main import create_app
from jarvis.prefs import Prefs
from jarvis.router.normalize import strip_fillers
from jarvis.voice.tts import TextToSpeech
from jarvis.voice.wake import FRAME, RATE, Segmenter, WakeListener, match_wake


@pytest.mark.parametrize("heard,rest", [
    ("Hello Archu.", ""),
    ("Hello, Archu!", ""),
    ("hey archoo", ""),
    ("Archu", ""),
    ("Hello Arch you", ""),
    ("Hello Archu, open Gmail.", "open Gmail"),
    ("Hello Archu volume badhao", "volume badhao"),
    ("Archu, play the second video", "play the second video"),
])
def test_wake_phrase_variants(heard, rest):
    assert match_wake(heard) == (True, rest)


@pytest.mark.parametrize("heard", ["Hello everyone", "search archu songs", "I was at the church", "hello", ""])
def test_not_a_wake_phrase(heard):
    assert match_wake(heard)[0] is False


def test_typed_name_is_stripped_only_as_a_call():
    assert strip_fillers("Hello Archu, open gmail") == "open gmail"
    assert strip_fillers("Archu open notepad") == "open notepad"


def _tone(seconds, amp):
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _frames(audio):
    return [audio[i:i + FRAME] for i in range(0, len(audio) - FRAME + 1, FRAME)]


def test_segmenter_cuts_speech_between_silences():
    rng = np.random.default_rng(0)
    quiet = lambda s: (rng.normal(0, 0.002, int(s * RATE))).astype(np.float32)  # noqa: E731
    audio = np.concatenate([quiet(1.0), _tone(1.2, 0.2), quiet(1.0), _tone(0.1, 0.2), quiet(1.0)])
    seg = Segmenter()
    out = [s for f in _frames(audio) if (s := seg.feed(f)) is not None]
    assert len(out) == 1  # the 0.1 s click is too short to count
    assert 1.1 <= len(out[0]) / RATE <= 2.3


def test_segmenter_caps_long_speech():
    seg = Segmenter(max_s=2.0)
    out = [s for f in _frames(_tone(5.0, 0.2)) if (s := seg.feed(f)) is not None]
    assert out and all(len(s) / RATE <= 2.1 for s in out)


# ---------- voices ----------

def test_chosen_voice_used_then_offline_fallback():
    said = []

    def edge(text, voice):
        raise OSError("no internet")

    def onecore(text, voice):
        if voice == "Heera":
            raise RuntimeError("voice Heera is not installed")
        said.append(voice)

    prefs = Prefs(None)
    tts = TextToSpeech(prefs, engines={"edge": edge, "onecore": onecore}, start=False)
    assert tts.say_now("hi") == "zira" and said == ["Zira"]
    assert "swara failed" in tts.last_fallback and "used zira" in tts.last_fallback
    prefs.update(voice="zira")
    assert tts.say_now("hi") == "zira" and tts.last_fallback is None


def test_tts_busy_while_speaking():
    gate = threading.Event()
    tts = TextToSpeech(Prefs(None), engines={"edge": lambda t, v: gate.wait(2), "onecore": lambda t, v: None})
    asyncio.run(tts.speak("hello"))
    time.sleep(0.1)
    assert tts.busy()
    gate.set()
    time.sleep(0.3)
    assert tts.busy(tail_s=5) and not tts.busy(tail_s=0)


def test_prefs_persist(tmp_path):
    p = Prefs(tmp_path / "prefs.json")
    assert p.get("voice") == "swara" and p.get("wake_enabled") is True
    p.update(voice="heera", wake_enabled=False, junk=1)
    again = Prefs(tmp_path / "prefs.json")
    assert again.all() == {"voice": "heera", "wake_enabled": False}


def test_prefs_api(make_jarvis, settings):
    j = make_jarvis()
    j.prefs = Prefs(settings.data_dir / "prefs.json")
    j.tts = TextToSpeech(j.prefs, engines={"edge": lambda t, v: None, "onecore": lambda t, v: None}, start=False)
    with TestClient(create_app(settings, jarvis=j)) as c:
        r = c.get("/api/prefs").json()
        assert [v["id"] for v in r["voices"]] == ["swara", "neerja", "heera", "zira"]
        assert c.post("/api/prefs", json={"voice": "neerja"}).json()["prefs"]["voice"] == "neerja"
        assert c.post("/api/prefs", json={"voice": "alexa"}).status_code == 400
        assert c.post("/api/voice/test", json={"voice": "swara"}).json()["voice"] == "swara"


# ---------- listener loop with a fake microphone ----------

class FakeStream:
    def __init__(self, audio):
        self.frames = _frames(audio)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self, n):
        if not self.frames:
            time.sleep(0.01)
            return np.zeros((n, 1), np.float32), False
        return self.frames.pop(0).reshape(-1, 1), False


class FakeSTT:
    def __init__(self, texts):
        self.texts = list(texts)

    def transcribe_array(self, audio, prompt=None):
        return self.texts.pop(0) if self.texts else ""


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, t, **d):
        self.events.append((t, d))

    def set_state(self, s):
        self.events.append(("state", {"state": s}))


async def _run_listener(texts, utterances, wake_texts=None, window_s=8.0, settle_s=0.05):
    rng = np.random.default_rng(1)
    parts = [rng.normal(0, 0.002, RATE).astype(np.float32)]
    for _ in range(utterances):
        parts += [_tone(1.0, 0.2), rng.normal(0, 0.002, RATE).astype(np.float32)]
    commands, bus, attention = [], Bus(), []

    async def on_command(text):
        commands.append(("command", text))
        attention.append(("command", text))

    async def attend(on):
        attention.append(("attention", on))

    wake_stt = FakeSTT(wake_texts) if wake_texts is not None else None
    w = WakeListener(FakeSTT(texts), None, bus, on_command, asyncio.get_running_loop(),
                     stream_factory=lambda: FakeStream(np.concatenate(parts)), wake_stt=wake_stt,
                     attention=attend, chime=None, command_window_s=window_s)
    w.start()
    for _ in range(400):
        await asyncio.sleep(0.01)
        if commands:
            break
    await asyncio.sleep(settle_s)
    w.stop()
    return [c for _, c in commands], bus, attention


async def test_wake_then_command_in_two_breaths():
    # the small wake model hears "Hello Archu", the command model hears the command
    commands, bus, attention = await _run_listener(["open gmail"], utterances=2, wake_texts=["Hello Archu."])
    assert commands == ["open gmail"]
    assert any(t == "wake" for t, _ in bus.events)
    # media is paused/ducked while listening and restored before the command runs
    assert attention == [("attention", True), ("attention", False), ("command", "open gmail")]


async def test_wake_alone_then_silence_restores_media():
    commands, bus, attention = await _run_listener([], utterances=1, wake_texts=["Hello Archu."], window_s=0.3,
                                                   settle_s=1.5)
    assert commands == [] and attention == [("attention", True), ("attention", False)]
    assert any(t == "wake_timeout" for t, _ in bus.events)


async def test_wake_and_command_in_one_breath():
    commands, _, attention = await _run_listener(["Hello Archu, what time is it?"], utterances=1)
    assert commands == ["what time is it"] and ("attention", True) not in attention


async def test_other_speech_is_ignored():
    commands, bus, _ = await _run_listener(["I think we should order pizza."], utterances=1, settle_s=0.5)
    assert commands == [] and not any(t == "wake" for t, _ in bus.events)


@pytest.mark.parametrize("heard,want", [
    ("Video Paws Carro.", "Video pause karo."),
    ("Skip Add", "Skip ad"),
    ("skip the adds", "skip the ad"),
    ("add a note to my list", "add a note to my list"),  # "add" alone is left alone
    ("Paws the music", "pause the music"),
])
def test_fix_transcript(heard, want):
    from jarvis.voice.stt import fix_transcript
    assert fix_transcript(heard) == want


def test_misheard_voice_commands_route_locally(make_jarvis):
    from jarvis.voice.stt import fix_transcript
    j = make_jarvis(responder=lambda s, u: pytest.fail("planner called"))
    for heard, workflow in (("Skip Add.", "skip_ad"), ("Video Paws Carro.", "media_control")):
        d = j.router.route_local(fix_transcript(heard))
        assert d is not None and d.workflow.name == workflow, heard
