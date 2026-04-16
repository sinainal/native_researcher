"""Project-scoped workspace state schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.article import Article
from app.schemas.pubmed import PubMedSearchMeta
from app.schemas.pubmed import SearchResource


class ProjectSearchPayload(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    year_start: int | None = Field(default=None, ge=1000, le=9999)
    year_end: int | None = Field(default=None, ge=1000, le=9999)
    max_results: int = Field(default=20, ge=1, le=5000)
    batch_size: int | None = Field(default=None, ge=1, le=500)
    min_cite: int | None = Field(default=None, ge=0, le=1000000)
    article_type: str | None = Field(default=None, max_length=200)
    use_cache: bool = True
    preferred_source: SearchResource = "pubmed"


class ProjectQueryRecord(BaseModel):
    id: str = Field(..., min_length=1, max_length=120)
    title: str = Field(..., min_length=1, max_length=200)
    created_at: str = Field(..., min_length=1, max_length=64)
    updated_at: str = Field(..., min_length=1, max_length=64)
    search_payload: ProjectSearchPayload
    meta: PubMedSearchMeta | None = None
    articles: list[Article] = Field(default_factory=list)


class ProjectStatePayload(BaseModel):
    active_query_id: str | None = Field(default=None, max_length=120)
    selected_query_ids: list[str] = Field(default_factory=list)
    selected_ids: list[int] = Field(default_factory=list)
    detail_article_id: int | None = Field(default=None, ge=1)
    sidebar_panel: str = Field(default="queries", max_length=32)
    query_detail_id: str | None = Field(default=None, max_length=120)
    downloadability_cache: dict[str, dict[str, Any]] = Field(default_factory=dict)
    query_history: list[ProjectQueryRecord] = Field(default_factory=list)
    current_session_id: str | None = Field(default=None, max_length=120)
    assistant_sessions: list[dict[str, Any]] = Field(default_factory=list)
