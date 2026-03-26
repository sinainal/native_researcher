"""Schemas for batch LLM article processing."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class LLMArticle(BaseModel):
    id: int = Field(..., ge=1)
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
    doi: str | None = None
    pmid: str | None = None
    pmc_id: str | None = None


class LLMProcessRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    prompt: str = Field(default="", max_length=24000)
    model: str | None = Field(default=None, max_length=100)
    analysis_mode: Literal["custom", "screen_for_question"] = "custom"
    question: str | None = Field(default=None, max_length=4000)
    output_schema: dict[str, Any] | None = None
    selected_ids: list[int] = Field(default_factory=list)
    articles: list[LLMArticle] = Field(default_factory=list)
    max_abstract_tokens: int = Field(default=750, ge=50, le=5000)
    llm_batch: int = Field(default=25, ge=1, le=100)
    dynamic_batch: bool = False
    retry_count: int = Field(default=3, ge=0, le=10)
    top_k: int = Field(default=10, ge=1, le=250)

    @model_validator(mode="after")
    def validate_prompt_requirements(self) -> "LLMProcessRequest":
        if self.analysis_mode == "custom" and not self.prompt.strip():
            raise ValueError("prompt cannot be empty in custom analysis mode")
        if self.analysis_mode != "custom" and not ((self.question or "").strip() or self.prompt.strip()):
            raise ValueError("question cannot be empty in analyzer mode")
        return self


class LLMBatchReport(BaseModel):
    batch_number: int
    article_ids: list[int] = Field(default_factory=list)
    article_count: int = 0
    estimated_input_tokens: int = 0
    attempts: int = 1
    output_count: int = 0
    status: str = "success"
    error: str | None = None


class LLMProcessResponse(BaseModel):
    model: str
    analysis_mode: str = "custom"
    article_scope: str
    article_count: int
    batch_count: int
    processed_count: int
    merged_count: int
    top_article_ids: list[int] = Field(default_factory=list)
    aggregate_summary: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    batches: list[LLMBatchReport] = Field(default_factory=list)
    processed_articles: list[dict[str, Any]] = Field(default_factory=list)
