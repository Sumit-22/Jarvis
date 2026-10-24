"""Speech to text with faster-whisper on CPU (int8). Optional dependency: requirements-voice.txt."""
from __future__ import annotations

import asyncio
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


# English-only decoding mishears a few Hinglish / short command words; seen in measured transcripts.
_MISHEARD = [
    (re.compile(r"\bpaws\b", re.I), "pause"),
    (re.compile(r"\b(carro|caro|karro)\b", re.I), "karo"),
    (re.compile(r"\b(skip (?:the |this )?)adds?\b", re.I), r"\1ad"),  # "Skip Add" -> "skip ad"
]


def fix_transcript(text: str) -> str:
    for pattern, repl in _MISHEARD:
        text = pattern.sub(repl, text)
    return text


class SpeechToText:
    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self._model: Any = None
        self._lock = threading.Lock()  # the dashboard mic and the wake listener share one model

    def _load(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8", cpu_threads=4)
        return self._model

    def warm(self) -> None:
        """Load the model now (a few seconds) so the first voice command does not pay for it."""
        with self._lock:
            self._load()

    def transcribe_array(self, audio: Any, prompt: str | None = None) -> str:
        """16 kHz mono float32 samples -> text. English decoding keeps Hinglish romanised (no Devanagari).

        A prompt makes whisper "hear" it in plain noise (a 220 Hz tone came out as "Hello Archu."), so
        non-speech is cut by whisper's VAD and unsure segments are dropped. Measured on 12 wake phrases in
        3 Indian voices + 10 noise clips: 12/12 wakes, 0 false wakes (without the VAD: 4/10 noise clips woke it).
        """
        with self._lock:
            segments, _ = self._load().transcribe(audio, beam_size=1, language="en", initial_prompt=prompt,
                                                  vad_filter=True, condition_on_previous_text=False)
            return fix_transcript(" ".join(s.text.strip() for s in segments
                                           if s.no_speech_prob <= 0.5 and s.avg_logprob >= -1.0).strip())

    def _transcribe_file(self, path: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        model = self._load()
        with self._lock:
            # language="en": no language-detection pass, and Hinglish stays romanised (same as transcribe_array)
            segments, info = model.transcribe(path, beam_size=1, language="en", vad_filter=True,
                                              condition_on_previous_text=False)
            text = fix_transcript(" ".join(s.text.strip() for s in segments).strip())
        return {"text": text, "language": info.language, "latency_s": round(time.perf_counter() - t0, 2)}

    async def transcribe(self, audio: bytes, suffix: str = ".webm") -> dict[str, Any]:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio)
            path = f.name
        try:
            return await asyncio.to_thread(self._transcribe_file, path)
        finally:
            Path(path).unlink(missing_ok=True)
