"""Cancellation tokens, one per running execution."""
from __future__ import annotations

import asyncio


class CancelToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


class CancelRegistry:
    def __init__(self) -> None:
        self._tokens: dict[str, CancelToken] = {}

    def create(self, execution_id: str) -> CancelToken:
        tok = CancelToken()
        self._tokens[execution_id] = tok
        return tok

    def cancel(self, execution_id: str) -> bool:
        tok = self._tokens.get(execution_id)
        if tok is None:
            return False
        tok.cancel()
        return True

    def cancel_all(self) -> int:
        for t in self._tokens.values():
            t.cancel()
        return len(self._tokens)

    def remove(self, execution_id: str) -> None:
        self._tokens.pop(execution_id, None)
