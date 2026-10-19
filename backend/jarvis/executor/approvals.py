"""Approval gate: a run pauses until the UI approves or denies; timeout means cancelled."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any


class ApprovalManager:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self.details: dict[str, dict[str, Any]] = {}

    def request(self, detail: dict[str, Any]) -> tuple[str, asyncio.Future[bool]]:
        aid = uuid.uuid4().hex[:10]
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[aid] = fut
        self.details[aid] = detail
        return aid, fut

    def resolve(self, approval_id: str, approved: bool) -> bool:
        fut = self._pending.pop(approval_id, None)
        self.details.pop(approval_id, None)
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True

    def discard(self, approval_id: str) -> None:
        self._pending.pop(approval_id, None)
        self.details.pop(approval_id, None)

    def pending(self) -> list[dict[str, Any]]:
        return [{"approval_id": k, **v} for k, v in self.details.items()]
