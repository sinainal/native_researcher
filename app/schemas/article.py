"""Shared article schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Article(BaseModel):
    id: int = Field(..., ge=1)
    source_name: str | None = None
    source_record_id: str | None = None
    pmid: str
    title: str
    abstract: str = ""
    year: str | None = None
    journal: str | None = None
    publication_date: str | None = None
    article_type: str | None = None
    article_types: list[str] = Field(default_factory=list)
    citation_count: int | None = None
    authors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    mesh_terms: list[str] = Field(default_factory=list)
    related_articles: list[str] = Field(default_factory=list)
    reference_count: int = 0
    doi: str | None = None
    pmc_id: str | None = None
    oa_pdf_url: str | None = None
    landing_page_url: str | None = None
    issn_l: str | None = None
    issns: list[str] = Field(default_factory=list)
    journal_quartile: str | None = None
    journal_metric_year: int | None = None
    journal_sjr: float | None = None
    journal_metrics_source: str | None = None
    research_meta: dict[str, Any] = Field(default_factory=dict)


class ArticleReference(BaseModel):
    source_name: str | None = None
    source_record_id: str | None = None
    title: str | None = None
    year: str | None = None
    journal: str | None = None
    doi: str | None = None
    pmc_id: str | None = None
    pmid: str | None = None
    oa_pdf_url: str | None = None
    landing_page_url: str | None = None
