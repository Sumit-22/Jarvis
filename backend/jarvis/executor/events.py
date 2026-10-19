"""In-process event bus. The WebSocket forwards every event to the UI; the UI never infers state."""
from __future__ import annotations

import asyncio
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()
        self.state = "idle"  # idle | listening | planning | executing | error
        self.history: list[dict[str, Any]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.discard(q)

    def emit(self, type_: str, **data: Any) -> None:
        if type_ == "state":
            self.state = data["state"]
        event = {"type": type_, **data}
        self.history = (self.history + [event])[-200:]
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def set_state(self, state: str, **data: Any) -> None:
        self.emit("state", state=state, **data)
