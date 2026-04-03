"""Local journal metrics bootstrap and lookup."""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

import httpx
import pandas as pd

from app.core.config import Settings
from app.schemas.article import Article
from app.services.workspace_db import WorkspaceDatabase


@dataclass(frozen=True)
class JournalMetricRecord:
    journal_name: str
    normalized_name: str
    metric_year: int
    best_quartile: str | None
    sjr: float | None
    sourceid: str | None
    categories: str
    areas: str
    source_name: str


class JournalMetricsService:
    def __init__(
        self,
        database: WorkspaceDatabase,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.http_client = http_client
        self._by_issn: dict[str, JournalMetricRecord] = {}
        self._by_name: dict[str, JournalMetricRecord] = {}

    async def ensure_bootstrap(self) -> None:
        if not self.settings.journal_metrics_enabled:
            return
        if not self._has_bootstrapped_data() and self.http_client is not None:
            try:
                await self._bootstrap_from_remote()
            except Exception:
                return
        self._load_indexes()

    def enrich_articles(self, articles: list[Article]) -> None:
        if not self.settings.journal_metrics_enabled:
            return
        if not self._by_issn and not self._by_name:
            self._load_indexes()
        for article in articles:
            match = self.lookup(article)
            if match is None:
                continue
            article.journal_quartile = match.best_quartile
            article.journal_metric_year = match.metric_year
            article.journal_sjr = match.sjr
            article.journal_metrics_source = match.source_name

    def lookup(self, article: Article) -> JournalMetricRecord | None:
        issn_keys = []
        if article.issn_l:
            issn_keys.append(self._normalize_issn(article.issn_l))
        for item in article.issns:
            normalized = self._normalize_issn(item)
            if normalized:
                issn_keys.append(normalized)
        seen: set[str] = set()
        for key in issn_keys:
            if not key or key in seen:
                continue
            seen.add(key)
            record = self._by_issn.get(key)
            if record is not None:
                return record
        normalized_name = self._normalize_journal_name(article.journal or "")
        if normalized_name:
            return self._by_name.get(normalized_name)
        return None

    def _has_bootstrapped_data(self) -> bool:
        row = self.database.fetchone(
            """
            SELECT row_count
            FROM journal_metrics_meta
            WHERE source_name = ?
            """,
            (self.settings.journal_metrics_source_name,),
        )
        return bool(row and int(row["row_count"] or 0) > 0)

    async def _bootstrap_from_remote(self) -> None:
        if self.http_client is None:
            return
        response = await self.http_client.get(self.settings.journal_metrics_bootstrap_url)
        response.raise_for_status()
        dataframe = pd.read_excel(io.BytesIO(response.content))
        metric_year = self._detect_metric_year(dataframe.columns)
        rows = list(self._records_from_dataframe(dataframe, metric_year))
        timestamp = datetime.now(UTC).isoformat()
        with self.database.transaction() as conn:
            conn.execute(
                "DELETE FROM journal_metrics WHERE source_name = ?",
                (self.settings.journal_metrics_source_name,),
            )
            conn.executemany(
                """
                INSERT INTO journal_metrics (
                    issn_l,
                    issn,
                    normalized_name,
                    journal_name,
                    metric_year,
                    best_quartile,
                    sjr,
                    sourceid,
                    categories,
                    areas,
                    source_name,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["issn_l"],
                        row["issn"],
                        row["normalized_name"],
                        row["journal_name"],
                        row["metric_year"],
                        row["best_quartile"],
                        row["sjr"],
                        row["sourceid"],
                        row["categories"],
                        row["areas"],
                        self.settings.journal_metrics_source_name,
                        timestamp,
                    )
                    for row in rows
                ],
            )
            conn.execute(
                """
                INSERT INTO journal_metrics_meta(source_name, bootstrap_url, metric_year, row_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    bootstrap_url = excluded.bootstrap_url,
                    metric_year = excluded.metric_year,
                    row_count = excluded.row_count,
                    updated_at = excluded.updated_at
                """,
                (
                    self.settings.journal_metrics_source_name,
                    self.settings.journal_metrics_bootstrap_url,
                    metric_year,
                    len(rows),
                    timestamp,
                ),
            )

    def _load_indexes(self) -> None:
        rows = self.database.fetchall(
            """
            SELECT issn_l, issn, normalized_name, journal_name, metric_year, best_quartile, sjr,
                   sourceid, categories, areas, source_name
            FROM journal_metrics
            WHERE source_name = ?
            """,
            (self.settings.journal_metrics_source_name,),
        )
        by_issn: dict[str, JournalMetricRecord] = {}
        by_name: dict[str, JournalMetricRecord] = {}
        for row in rows:
            record = JournalMetricRecord(
                journal_name=str(row["journal_name"] or ""),
                normalized_name=str(row["normalized_name"] or ""),
                metric_year=int(row["metric_year"] or 0),
                best_quartile=str(row["best_quartile"] or "").strip() or None,
                sjr=float(row["sjr"]) if row["sjr"] is not None else None,
                sourceid=str(row["sourceid"] or "").strip() or None,
                categories=str(row["categories"] or ""),
                areas=str(row["areas"] or ""),
                source_name=str(row["source_name"] or self.settings.journal_metrics_source_name),
            )
            issn_l = self._normalize_issn(row["issn_l"])
            issn = self._normalize_issn(row["issn"])
            if issn_l:
                existing = by_issn.get(issn_l)
                if existing is None or self._is_better(record, existing):
                    by_issn[issn_l] = record
            if issn:
                existing = by_issn.get(issn)
                if existing is None or self._is_better(record, existing):
                    by_issn[issn] = record
            if record.normalized_name:
                existing = by_name.get(record.normalized_name)
                if existing is None or self._is_better(record, existing):
                    by_name[record.normalized_name] = record
        self._by_issn = by_issn
        self._by_name = by_name

    @classmethod
    def _records_from_dataframe(cls, dataframe: pd.DataFrame, metric_year: int) -> Iterable[dict[str, object]]:
        for _, row in dataframe.iterrows():
            journal_name = str(row.get("Title") or "").strip()
            if not journal_name:
                continue
            normalized_name = cls._normalize_journal_name(journal_name)
            issns = cls._parse_issns(row.get("Issn"))
            issn_l = issns[0] if issns else None
            quartile = cls._normalize_quartile(row.get("SJR Best Quartile"))
            sjr = cls._safe_float(row.get("SJR"))
            sourceid = str(row.get("Sourceid") or "").strip() or None
            categories = str(row.get("Categories") or "").strip()
            areas = str(row.get("Areas") or "").strip()
            if issns:
                for issn in issns:
                    yield {
                        "issn_l": issn_l,
                        "issn": issn,
                        "normalized_name": normalized_name,
                        "journal_name": journal_name,
                        "metric_year": metric_year,
                        "best_quartile": quartile,
                        "sjr": sjr,
                        "sourceid": sourceid,
                        "categories": categories,
                        "areas": areas,
                    }
            else:
                yield {
                    "issn_l": None,
                    "issn": None,
                    "normalized_name": normalized_name,
                    "journal_name": journal_name,
                    "metric_year": metric_year,
                    "best_quartile": quartile,
                    "sjr": sjr,
                    "sourceid": sourceid,
                    "categories": categories,
                    "areas": areas,
                }

    @staticmethod
    def _detect_metric_year(columns: Iterable[object]) -> int:
        for column in columns:
            match = re.search(r"\((\d{4})\)", str(column))
            if match:
                return int(match.group(1))
        return datetime.now(UTC).year

    @staticmethod
    def _parse_issns(raw: object) -> list[str]:
        values: list[str] = []
        for item in str(raw or "").split(","):
            normalized = JournalMetricsService._normalize_issn(item)
            if normalized and normalized not in values:
                values.append(normalized)
        return values

    @staticmethod
    def _normalize_issn(value: object) -> str | None:
        text = str(value or "").strip().upper()
        if not text:
            return None
        normalized = re.sub(r"[^0-9X]", "", text)
        return normalized or None

    @staticmethod
    def _normalize_journal_name(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        normalized = re.sub(r"\bthe\b", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @staticmethod
    def _normalize_quartile(value: object) -> str | None:
        text = str(value or "").strip().upper()
        return text if text in {"Q1", "Q2", "Q3", "Q4"} else None

    @staticmethod
    def _safe_float(value: object) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(parsed):
            return None
        return parsed

    @staticmethod
    def _quartile_rank(value: str | None) -> int:
        return {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3}.get(value or "", 99)

    @classmethod
    def _is_better(cls, candidate: JournalMetricRecord, current: JournalMetricRecord) -> bool:
        candidate_key = (
            cls._quartile_rank(candidate.best_quartile),
            -(candidate.sjr or 0.0),
            -candidate.metric_year,
        )
        current_key = (
            cls._quartile_rank(current.best_quartile),
            -(current.sjr or 0.0),
            -current.metric_year,
        )
        return candidate_key < current_key
