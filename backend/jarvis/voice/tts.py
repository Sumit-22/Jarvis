"""Offline text to speech with pyttsx3 (Windows SAPI)."""
from __future__ import annotations

import asyncio
import threading


class TextToSpeech:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _say(self, text: str) -> None:
        import pyttsx3
        with self._lock:  # pyttsx3 engines are not thread safe; create one per utterance
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            engine.stop()

    async def speak(self, text: str) -> None:
        await asyncio.to_thread(self._say, text)
