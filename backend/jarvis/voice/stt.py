"""Speech to text with faster-whisper on CPU (int8). Optional dependency: requirements-voice.txt."""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Any


class SpeechToText:
    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def _transcribe_file(self, path: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        model = self._load()
        segments, info = model.transcribe(path, beam_size=1, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"text": text, "language": info.language, "latency_s": round(time.perf_counter() - t0, 2)}

    async def transcribe(self, audio: bytes, suffix: str = ".webm") -> dict[str, Any]:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio)
            path = f.name
        try:
            return await asyncio.to_thread(self._transcribe_file, path)
        finally:
            Path(path).unlink(missing_ok=True)
