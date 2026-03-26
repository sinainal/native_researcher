"""Small in-memory TTL cache."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    def __init__(self, ttl_seconds: int, max_entries: int = 128) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._store: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired_keys = [
            key
            for key, (expires_at, _) in self._store.items()
            if expires_at <= now
        ]
        for key in expired_keys:
            self._store.pop(key, None)

    def get(self, key: K) -> V | None:
        self._purge_expired()
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at <= time.monotonic():
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: K, value: V) -> None:
        self._purge_expired()
        self._store[key] = (time.monotonic() + self.ttl_seconds, value)
        self._store.move_to_end(key)
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)

    def delete(self, key: K) -> None:
        self._store.pop(key, None)
