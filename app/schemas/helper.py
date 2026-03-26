"""Helper AI chat schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HelperArticle(BaseModel):
    id: int = Field(..., ge=1)
    title: str
    year: str | None = None
    article_type: str | None = None
    citation_count: int | None = None
    mesh_terms: list[str] = Field(default_factory=list)
    abstract: str = ""
    pmid: str | None = None
    doi: str | None = None
    journal: str | None = None


class HelperChatRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    message: str = Field(..., min_length=1, max_length=12000)
    model: str | None = Field(default=None, max_length=100)
    thread_id: str | None = Field(default=None, max_length=100)
    mode: str = Field(default="fast", max_length=20)
    thinking_level: str = Field(default="off", max_length=20)
    selected_ids: list[int] = Field(default_factory=list)
    articles: list[HelperArticle] = Field(default_factory=list)


class HelperExecutedAction(BaseModel):
    type: str
    name: str
    title: str
    status: str = "success"
    details: dict[str, Any] = Field(default_factory=dict)


class HelperChatResponse(BaseModel):
    thread_id: str
    answer: str
    model: str
    mode: str = "fast"
    used_article_ids: list[int] = Field(default_factory=list)
    history_size: int = 0
    thinking: str | None = None
    executed_actions: list[HelperExecutedAction] = Field(default_factory=list)


class HelperResetRequest(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=100)
