"""Shared article schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Article(BaseModel):
    id: int = Field(..., ge=1)
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


class ArticleReference(BaseModel):
    title: str | None = None
    year: str | None = None
    doi: str | None = None
    pmc_id: str | None = None
    pmid: str | None = None
