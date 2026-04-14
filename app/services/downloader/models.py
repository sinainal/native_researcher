"""Shared downloader models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DownloadCandidate:
    source: str
    url: str
    file_type: str
    priority: int


@dataclass
class AttemptRecord:
    step: str
    source: str
    url: str
    status: str
    elapsed_ms: int
    detail: str | None = None
    status_code: int | None = None
    content_type: str | None = None
