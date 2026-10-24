"""Text to speech on one background thread, so a run never waits on it.

Voices (picked in the dashboard, stored in prefs):
- swara / neerja: Microsoft neural voices through edge-tts. Natural, but online: the text goes to
  Microsoft's speech service.
- heera / zira: Windows OneCore voices through WinRT, offline. Heera needs the "English (India)" voice
  pack (Settings > Time & language > Speech > Add voices).
If the chosen voice fails (offline, not installed), the next offline voice is used and the reason is
kept in `last_fallback`. pyttsx3's runAndWait() was dropped: it hung after many utterances and blocked
the command response.
"""
from __future__ import annotations

import asyncio
import ctypes
import os
import queue
import tempfile
import threading
import time
from typing import Any, Callable

VOICES: list[dict[str, Any]] = [
    {"id": "swara", "label": "Swara", "detail": "Hindi · natural · online", "engine": "edge", "voice": "hi-IN-SwaraNeural"},
    {"id": "neerja", "label": "Neerja", "detail": "Indian English · natural · online", "engine": "edge", "voice": "en-IN-NeerjaNeural"},
    {"id": "heera", "label": "Heera", "detail": "Indian English · offline", "engine": "onecore", "voice": "Heera"},
    {"id": "zira", "label": "Zira", "detail": "US English · offline", "engine": "onecore", "voice": "Zira"},
]
VOICE_IDS = [v["id"] for v in VOICES]
SAMPLE = "Namaste! Main Archu hoon. It's a quarter past three, and the volume is fifty percent."


def onecore_voice_names() -> list[str]:
    try:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        return [v.display_name for v in SpeechSynthesizer.all_voices]
    except Exception:
        return []


def voice_list() -> list[dict[str, Any]]:
    """VOICES with whether each can be used on this PC right now."""
    installed = onecore_voice_names()
    try:
        import edge_tts  # noqa: F401
        edge_ok = True
    except ImportError:
        edge_ok = False
    out = []
    for v in VOICES:
        if v["engine"] == "edge":
            ok, note = edge_ok, "" if edge_ok else "edge-tts not installed"
        else:
            ok = any(v["voice"] in n for n in installed)
            note = "" if ok else ("install 'English (India)' in Settings > Time & language > Speech"
                                  if v["id"] == "heera" else "not installed")
        out.append({**{k: v[k] for k in ("id", "label", "detail")}, "online": v["engine"] == "edge",
                    "available": ok, "note": note})
    return out


# ---------- engines (each blocks until the audio has played) ----------

def _play_mp3(path: str) -> None:
    mci = ctypes.windll.winmm.mciSendStringW  # type: ignore[attr-defined]
    alias = f"jarvis{threading.get_ident()}"
    buf = ctypes.create_unicode_buffer(256)
    if mci(f'open "{path}" type mpegvideo alias {alias}', buf, 255, 0) != 0:
        raise RuntimeError("could not open the audio for playback")
    try:
        mci(f"play {alias} wait", buf, 255, 0)
    finally:
        mci(f"close {alias}", buf, 255, 0)


def speak_edge(text: str, voice: str) -> None:
    import edge_tts
    fd, path = tempfile.mkstemp(suffix=".mp3", prefix="jarvis_tts_")
    os.close(fd)
    try:
        asyncio.run(asyncio.wait_for(edge_tts.Communicate(text, voice).save(path), timeout=15))
        if os.path.getsize(path) == 0:
            raise RuntimeError("no audio returned")
        _play_mp3(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def speak_onecore(text: str, voice: str) -> None:
    import winsound
    from winrt.windows.media.speechsynthesis import SpeechSynthesizer
    from winrt.windows.storage.streams import DataReader

    async def synth() -> bytes:
        s = SpeechSynthesizer()
        match = [v for v in SpeechSynthesizer.all_voices if voice in v.display_name]
        if not match:
            raise RuntimeError(f"voice {voice} is not installed")
        s.voice = match[0]
        stream = await s.synthesize_text_to_stream_async(text)
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(stream.size)
        data = bytearray(stream.size)
        reader.read_bytes(data)
        return bytes(data)

    winsound.PlaySound(asyncio.run(synth()), winsound.SND_MEMORY)


ENGINES: dict[str, Callable[[str, str], None]] = {"edge": speak_edge, "onecore": speak_onecore}


class TextToSpeech:
    def __init__(self, prefs: Any = None, engines: dict[str, Callable[[str, str], None]] | None = None,
                 start: bool = True) -> None:
        self.prefs = prefs
        self.engines = engines or ENGINES
        self._q: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self.speaking = threading.Event()
        self.last_end = 0.0  # monotonic time the last utterance finished (the wake listener ignores its echo)
        self.last_voice: str | None = None
        self.last_fallback: str | None = None
        if start:
            threading.Thread(target=self._worker, name="tts", daemon=True).start()

    def chosen(self) -> str:
        v = self.prefs.get("voice") if self.prefs is not None else None
        return v if v in VOICE_IDS else VOICE_IDS[0]

    def say_now(self, text: str, voice_id: str | None = None) -> str:
        """Speak synchronously with the chosen voice, falling back to offline voices. Returns the voice used."""
        first = voice_id or self.chosen()
        order = [first] + [v["id"] for v in VOICES if v["engine"] == "onecore" and v["id"] != first]
        errors = []
        self.speaking.set()
        try:
            for vid in order:
                v = next(x for x in VOICES if x["id"] == vid)
                try:
                    self.engines[v["engine"]](text, v["voice"])
                    self.last_voice = vid
                    self.last_fallback = None if vid == first else f"{first} failed ({errors[0]}); used {vid}"
                    return vid
                except Exception as e:
                    errors.append(f"{type(e).__name__}: {e}"[:160])
            self.last_fallback = "no voice worked: " + "; ".join(errors)
            raise RuntimeError(self.last_fallback)
        finally:
            self.last_end = time.monotonic()
            self.speaking.clear()

    def _worker(self) -> None:
        while True:
            text, voice = self._q.get()
            while not self._q.empty():  # only the latest line matters
                text, voice = self._q.get_nowait()
            try:
                self.say_now(text, voice)
            except Exception:
                pass  # TTS must never break anything

    def busy(self, tail_s: float = 0.6) -> bool:
        """True while speaking or just after (so the microphone does not hear JARVIS itself)."""
        return self.speaking.is_set() or not self._q.empty() or time.monotonic() - self.last_end < tail_s

    async def speak(self, text: str, voice: str | None = None) -> None:
        """Queue the text and return immediately."""
        self._q.put((text, voice))
