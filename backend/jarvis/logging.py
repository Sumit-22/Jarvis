"""JSON-lines logger. Every entry carries execution_id; secret-looking keys are redacted."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "COOKIE")
_lock = threading.Lock()
_log_dir: Path | None = None


def configure(log_dir: Path) -> None:
    global _log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_dir = log_dir


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if any(m in str(k).upper() for m in _SECRET_MARKERS) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def log(event: str, execution_id: str | None = None, **fields: Any) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "execution_id": execution_id,
        **redact(fields),
    }
    if _log_dir is None:
        return
    path = _log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    line = json.dumps(entry, default=str, ensure_ascii=False)
    with _lock, path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
