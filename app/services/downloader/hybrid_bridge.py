"""Hybrid downloader bridge.

MVP strategy:
- Keep the legacy exact-core downloader as the default path.
- Use article-downloader only as a targeted helper on known publisher families
  or as a bounded fallback when the real tool has a non-crossref mode available.
"""

from __future__ import annotations

from typing import Any

from app.schemas.article import ArticleReference
from app.services.downloader.article_downloader_bridge import ArticleDownloaderBridge
from app.services.downloader.legacy_bridge import ExactNewMethodBridge


class HybridDownloaderBridge:
    """Legacy-first orchestration with targeted article-downloader assistance."""

    def __init__(
        self,
        *,
        legacy_bridge: ExactNewMethodBridge,
        article_downloader_bridge: ArticleDownloaderBridge,
    ) -> None:
        self.legacy_bridge = legacy_bridge
        self.article_downloader_bridge = article_downloader_bridge

    @staticmethod
    def _attempts(payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw = payload.get("attempts") or []
        return list(raw) if isinstance(raw, list) else []

    @staticmethod
    def _candidate_count(payload: dict[str, Any]) -> int:
        try:
            return int(payload.get("candidate_count") or 0)
        except (TypeError, ValueError):
            return 0

    def _tool_modes(self, article: ArticleReference) -> list[str]:
        return self.article_downloader_bridge._modes_for(article)

    def _tool_has_targeted_mode(self, article: ArticleReference) -> bool:
        return any(mode != "crossref" for mode in self._tool_modes(article))

    def _prefers_tool_first(self, article: ArticleReference) -> bool:
        doi = (article.doi or "").strip().lower()
        journal = self.article_downloader_bridge._normalize_text(article.journal)
        return doi.startswith(("10.1038/", "10.1007/", "10.1186/")) or any(
            marker in journal
            for marker in (
                "scientific reports",
                "scientific data",
                "nature communications",
                "communications biology",
                "experimental molecular medicine",
                "experimental & molecular medicine",
                "bmc ",
            )
        )

    @staticmethod
    def _merge_candidate_payloads(*candidate_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for group in candidate_groups:
            for item in group:
                key = (str(item.get("source") or ""), str(item.get("url") or ""))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
        return merged

    def _merge_payloads(
        self,
        article: ArticleReference,
        *,
        primary: dict[str, Any],
        secondary: dict[str, Any] | None,
        tool_first: bool,
    ) -> dict[str, Any]:
        if primary.get("success"):
            return primary
        if secondary and secondary.get("success"):
            attempts = self._attempts(primary) + self._attempts(secondary)
            merged = dict(secondary)
            merged["attempts"] = attempts
            merged["candidate_count"] = self._candidate_count(primary) + self._candidate_count(secondary)
            merged["note"] = None
            return merged

        attempts = self._attempts(primary)
        candidate_count = self._candidate_count(primary)
        final_note = primary.get("note") or "no_successful_candidate"
        if secondary is not None:
            attempts += self._attempts(secondary)
            candidate_count += self._candidate_count(secondary)
            secondary_note = secondary.get("note")
            if final_note == "no_successful_candidate" and secondary_note:
                final_note = secondary_note

        return {
            "article": article.model_dump(),
            "mode": primary.get("mode") or (secondary or {}).get("mode") or "fast",
            "success": False,
            "source": None,
            "url": None,
            "file_path": None,
            "total_ms": int((primary.get("total_ms") or 0) + ((secondary or {}).get("total_ms") or 0)),
            "attempts": attempts,
            "candidate_count": candidate_count,
            "note": final_note if final_note else ("hybrid_tool_first_failed" if tool_first else "hybrid_legacy_first_failed"),
        }

    async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast") -> list[dict[str, Any]]:
        legacy_candidates = await self.legacy_bridge.resolve_candidates(article, mode=mode)
        if not self._tool_has_targeted_mode(article):
            return legacy_candidates
        tool_candidates = await self.article_downloader_bridge.resolve_candidates(article, mode=mode)
        if self._prefers_tool_first(article):
            return self._merge_candidate_payloads(tool_candidates, legacy_candidates)
        return self._merge_candidate_payloads(legacy_candidates, tool_candidates)

    async def run(
        self,
        article: ArticleReference,
        *,
        output_dir,
        mode: str = "fast",
        budget_seconds: float = 60.0,
    ) -> dict[str, Any]:
        tool_eligible = self._tool_has_targeted_mode(article)
        tool_first = tool_eligible and self._prefers_tool_first(article)

        if tool_first:
            tool_payload = await self.article_downloader_bridge.run(
                article,
                output_dir=output_dir,
                mode=mode,
                budget_seconds=budget_seconds,
            )
            if tool_payload.get("success"):
                return tool_payload
            legacy_payload = await self.legacy_bridge.run(
                article,
                output_dir=output_dir,
                mode=mode,
                budget_seconds=budget_seconds,
            )
            return self._merge_payloads(
                article,
                primary=tool_payload,
                secondary=legacy_payload,
                tool_first=True,
            )

        legacy_payload = await self.legacy_bridge.run(
            article,
            output_dir=output_dir,
            mode=mode,
            budget_seconds=budget_seconds,
        )
        if legacy_payload.get("success") or not tool_eligible:
            return legacy_payload

        tool_payload = await self.article_downloader_bridge.run(
            article,
            output_dir=output_dir,
            mode=mode,
            budget_seconds=budget_seconds,
        )
        return self._merge_payloads(
            article,
            primary=legacy_payload,
            secondary=tool_payload,
            tool_first=False,
        )
