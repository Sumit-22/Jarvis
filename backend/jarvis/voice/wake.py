"""Always-on wake phrase ("Hello Archu") on the local microphone.

Audio never leaves the PC: a simple energy detector cuts speech into short segments, local faster-whisper
transcribes them, and a fuzzy match looks for the wake phrase. "Hello Archu" alone -> JARVIS answers and
listens for the command; "Hello Archu, open gmail" -> runs the command straight away. While JARVIS itself
is speaking the microphone input is ignored.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
from collections import deque
from typing import Any, Callable

from rapidfuzz import fuzz

from .. import logging as jlog

RATE = 16000
FRAME = 480  # 30 ms
WAKE_NAMES = ("archu", "archoo", "aarchu", "archu.", "arcu", "aarchoo", "archoo.", "archu,")
GREETINGS = {"hello", "hallo", "helo", "hey", "hi", "ok", "okay", "hullo"}
# Biases whisper toward spelling the name and toward romanised Hinglish commands.
PROMPT = "Hello Archu. Hello Archu, open gmail. Archu, volume badhao. Hello Archu, youtube pe gaana chalao."


def _tokens(text: str) -> list[str]:
    return re.sub(r"[^\w\s']", " ", text.lower()).split()


def match_wake(text: str) -> tuple[bool, str]:
    """-> (woke, the command said after the wake phrase, if any)."""
    toks = _tokens(text)
    for i, t in enumerate(toks[:3]):
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        one = 100.0 if t in WAKE_NAMES else fuzz.ratio(t, "archu")
        two = max(fuzz.ratio(t + nxt, "archu"), fuzz.ratio(t + nxt, "archyou")) if nxt else 0.0  # "arch you"
        pair = two >= 85 and two >= one
        single = not pair and one >= 80
        if not (single or pair):
            continue
        if i > 0 and toks[i - 1] not in GREETINGS:
            continue  # "search archu ..." is not a call
        rest_tokens = toks[i + (1 if single else 2):]
        if not rest_tokens:
            return True, ""
        words = text.split()  # keep the user's own wording (case, symbols) for the command when possible
        rest = " ".join(words[-len(rest_tokens):]) if len(words) == len(toks) else " ".join(rest_tokens)
        return True, rest.strip(" ,.!?")
    return False, ""


class Segmenter:
    """Energy-based speech segmentation with an adaptive noise floor (pure; fed 30 ms float frames)."""

    def __init__(self, max_s: float = 4.0, end_silence_s: float = 0.7, min_s: float = 0.35):
        self.max_frames = int(max_s * RATE / FRAME)
        self.end_frames = int(end_silence_s * RATE / FRAME)
        self.min_frames = int(min_s * RATE / FRAME)
        self.floor = 0.004
        self.pre: deque[Any] = deque(maxlen=10)  # 300 ms of audio before speech starts
        self.buf: list[Any] = []
        self.silent = 0
        self.loud_run = 0
        self.voiced = 0  # loud frames in the current segment

    def reset(self) -> None:
        self.buf, self.silent, self.loud_run, self.voiced = [], 0, 0, 0
        self.pre.clear()

    def feed(self, frame: Any) -> Any | None:
        """Returns a finished segment (numpy float32) or None."""
        import numpy as np
        rms = float(np.sqrt(np.mean(frame * frame)) + 1e-9)
        threshold = max(0.01, self.floor * 3.0)
        loud = rms > threshold
        if not self.buf:
            if loud:
                self.loud_run += 1
                self.pre.append(frame)
                if self.loud_run >= 3:  # 90 ms of sound starts a segment
                    self.buf = list(self.pre)
                    self.silent = 0
                    self.voiced = self.loud_run
            else:
                self.loud_run = 0
                self.floor = 0.95 * self.floor + 0.05 * rms
                self.pre.append(frame)
            return None
        self.buf.append(frame)
        self.silent = 0 if loud else self.silent + 1
        self.voiced += int(loud)
        if self.silent >= self.end_frames or len(self.buf) >= self.max_frames:
            seg, voiced = self.buf, self.voiced
            self.reset()
            if voiced >= self.min_frames:  # a cough or a click is too short to be words
                return np.concatenate(seg)
        return None


def _chime() -> None:
    """Short rising two-note 'ting' (~0.2 s): instant, unlike a spoken reply that blocks the mic for seconds."""
    import winsound
    winsound.Beep(988, 90)
    winsound.Beep(1319, 110)


class WakeListener:
    """`wake_stt` (a small model) checks every segment for the wake phrase; `stt` transcribes the command.
    `attention(True/False)` is awaited around listening for a command (pause media, lower the volume)."""

    def __init__(self, stt: Any, tts: Any, bus: Any, on_command: Callable[[str], Any],
                 loop: asyncio.AbstractEventLoop, stream_factory: Callable[..., Any] | None = None,
                 wake_stt: Any = None, attention: Callable[[bool], Any] | None = None,
                 chime: Callable[[], None] | None = _chime, command_window_s: float = 8.0):
        self.stt, self.tts, self.bus, self.on_command, self.loop = stt, tts, bus, on_command, loop
        self.wake_stt = wake_stt or stt
        self.attention, self.chime, self.command_window_s = attention, chime, command_window_s
        self.stream_factory = stream_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        self.mic: str | None = None
        self.last_heard: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self.error = None
        self._thread = threading.Thread(target=self._run, name="wake", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None

    def status(self) -> dict[str, Any]:
        return {"running": self.running, "error": self.error, "mic": self.mic, "last_heard": self.last_heard}

    # -- thread --------------------------------------------------------
    def _emit(self, t: str, **d: Any) -> None:
        self.loop.call_soon_threadsafe(lambda: self.bus.emit(t, **d))

    def _state(self, s: str) -> None:
        self.loop.call_soon_threadsafe(lambda: self.bus.set_state(s))

    def _attend(self, on: bool) -> None:
        if self.attention is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.attention(on), self.loop).result(timeout=4)
        except Exception as e:  # media control must never stop the listener
            jlog.log("wake_attention_failed", on=on, error=str(e))

    def _open(self) -> Any:
        if self.stream_factory is not None:
            return self.stream_factory()
        import sounddevice as sd
        self.mic = sd.query_devices(kind="input")["name"]
        return sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=FRAME)

    def _run(self) -> None:
        warm = getattr(self.wake_stt, "warm", None)
        if warm is not None:  # load the wake model before listening, so the first "Hello Archu" is not slow
            try:
                warm()
            except Exception as e:
                jlog.log("wake_warm_failed", error=str(e))
        try:
            stream = self._open()
        except Exception as e:
            self.error = f"microphone unavailable: {e}"
            self._emit("warning", message=f"Wake word off: {self.error}")
            return
        try:
            with stream:
                self._loop(stream)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            jlog.log("wake_failed", error=self.error)
            self._emit("warning", message=f"Wake word stopped: {self.error}")

    def _loop(self, stream: Any) -> None:
        seg = Segmenter()
        command_until = 0.0  # after "Hello Archu" alone, the next segment is the command
        while not self._stop.is_set():
            frame, _ = stream.read(FRAME)
            if self.tts is not None and self.tts.busy():
                seg.reset()
                continue
            if command_until and time.monotonic() > command_until and not seg.buf:
                command_until, seg = 0.0, Segmenter()
                self._attend(False)
                self._state("idle")
                self._emit("wake_timeout")
            audio = seg.feed(frame[:, 0] if getattr(frame, "ndim", 1) > 1 else frame)
            if audio is None:
                continue
            command_mode = bool(command_until)
            t0 = time.perf_counter()
            model = self.stt if command_mode else self.wake_stt
            text = model.transcribe_array(audio, prompt=PROMPT).strip()
            jlog.log("wake_segment", seconds=round(len(audio) / RATE, 2), rms=round(float((audio ** 2).mean() ** 0.5), 4),
                     heard=text, stt_s=round(time.perf_counter() - t0, 2), command_mode=command_mode)
            if command_mode:
                command_until, seg = 0.0, Segmenter()
                self._attend(False)
                if text:
                    self.last_heard = text
                    woke, rest = match_wake(text)
                    self._dispatch(rest if woke and rest else text)
                else:
                    self._state("idle")
                    self._emit("wake_timeout")
                continue
            if not text:
                continue
            self.last_heard = text
            woke, rest = match_wake(text)
            if not woke:
                continue
            jlog.log("wake", heard=text)
            self._emit("wake", heard=text)
            if rest:
                self._dispatch(rest)
                continue
            self._state("listening")
            self._attend(True)
            if self.chime is not None:
                try:
                    self.chime()
                except Exception:
                    pass
            seg = Segmenter(max_s=10.0, end_silence_s=0.9)
            command_until = time.monotonic() + self.command_window_s

    def _dispatch(self, text: str) -> None:
        self._emit("transcript", text=text, latency_s=0, source="wake")
        self._state("idle")
        asyncio.run_coroutine_threadsafe(self.on_command(text), self.loop)
