"""Structured downloader attempt logging."""

from __future__ import annotations

import time

from app.services.downloader.models import AttemptRecord


class DownloadLogger:
    def __init__(self) -> None:
        self._attempts: list[AttemptRecord] = []

    def record(
        self,
        *,
        step: str,
        source: str,
        url: str,
        status: str,
        started: float,
        detail: str | None = None,
        status_code: int | None = None,
        content_type: str | None = None,
    ) -> None:
        self._attempts.append(
            AttemptRecord(
                step=step,
                source=source,
                url=url,
                status=status,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                detail=detail,
                status_code=status_code,
                content_type=content_type,
            )
        )

    def export(self) -> list[dict[str, object | None]]:
        return [
            {
                "step": item.step,
                "source": item.source,
                "url": item.url,
                "status": item.status,
                "elapsed_ms": item.elapsed_ms,
                "detail": item.detail,
                "status_code": item.status_code,
                "content_type": item.content_type,
            }
            for item in self._attempts
        ]
