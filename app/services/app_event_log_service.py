"""Compact background event logging."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class AppEventLogService:
    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 256_000,
        keep_lines: int = 800,
    ) -> None:
        self.path = path
        self.max_bytes = max(16_384, int(max_bytes))
        self.keep_lines = max(100, int(keep_lines))
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        level: str,
        event: str,
        message: str = "",
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": self._trim(level or "info", 16).lower(),
            "event": self._trim(event or "event", 80),
            "message": self._trim(message or "", 240),
        }
        compact_context = self._compact_context(context or {})
        if compact_context:
            entry["context"] = compact_context
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._shrink_if_needed()
        return entry

    def _shrink_if_needed(self) -> None:
        try:
            if not self.path.exists() or self.path.stat().st_size <= self.max_bytes:
                return
            with self.path.open("r", encoding="utf-8") as handle:
                lines = deque(handle, maxlen=self.keep_lines)
            with self.path.open("w", encoding="utf-8") as handle:
                handle.writelines(lines)
        except OSError:
            return

    @classmethod
    def _compact_context(cls, context: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for index, (key, value) in enumerate(context.items()):
            if index >= 8:
                break
            normalized_key = cls._trim(str(key), 40)
            if isinstance(value, (bool, int, float)) or value is None:
                compact[normalized_key] = value
            else:
                compact[normalized_key] = cls._trim(str(value), 160)
        return compact

    @staticmethod
    def _trim(value: str, limit: int) -> str:
        normalized = str(value).strip()
        if len(normalized) <= limit:
            return normalized
        if limit <= 1:
            return normalized[:limit]
        return f"{normalized[:limit - 1]}…"

