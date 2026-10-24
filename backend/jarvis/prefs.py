"""User preferences changed from the dashboard (voice, wake word), kept in data/prefs.json.

Secrets never go here; .env stays the place for those.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {"voice": "swara", "wake_enabled": True}


class Prefs:
    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        if path is not None and path.is_file():
            try:
                self._data.update({k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if k in DEFAULTS})
            except (ValueError, OSError):
                pass

    def get(self, key: str) -> Any:
        return self._data.get(key, DEFAULTS.get(key))

    def all(self) -> dict[str, Any]:
        return dict(self._data)

    def update(self, **changes: Any) -> dict[str, Any]:
        with self._lock:
            self._data.update({k: v for k, v in changes.items() if k in DEFAULTS and v is not None})
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            return dict(self._data)
