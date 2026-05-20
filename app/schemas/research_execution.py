"""Research plan execution schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.article import Article
from app.schemas.pubmed import PubMedSearchMeta


class ResearchPlanExecuteRequest(BaseModel):
    plan: dict[str, Any] = Field(default_factory=dict)
    screening_model: str | None = Field(default=None, max_length=200)
    criteria_enabled: bool = True
    pdf_extractor_enabled: bool = True
    autoprocess: bool = True
    pdf_scope: Literal["selected", "selected_backup", "all"] = "selected_backup"
    full_text_model: str | None = Field(default=None, max_length=200)
    api_key: str = Field(default="", max_length=500)
    thinking_level: str = Field(default="off", max_length=32)


class ResearchQueryTrace(BaseModel):
    database: str
    source: str
    branch_id: str = ""
    branch_label: str = ""
    category_id: str = ""
    category_label: str = ""
    query: str
    raw_query: str = ""
    extracted_query: str = ""
    candidate_limit: int
    status: str = "success"
    fetched_results: int = 0
    total_results_found: int = 0
    request_count: int = 0
    elapsed_ms: int = 0
    error: str | None = None


class ResearchCandidateMatch(BaseModel):
    database: str
    source: str
    branch_id: str = ""
    branch_label: str = ""
    category_id: str = ""
    category_label: str = ""
    query: str = ""
    raw_query: str = ""
    extracted_query: str = ""


class ResearchCandidateTrace(BaseModel):
    candidate_id: str
    article_id: int
    title: str
    year: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmc_id: str | None = None
    source_names: list[str] = Field(default_factory=list)
    matches: list[ResearchCandidateMatch] = Field(default_factory=list)


class ResearchScreeningTrace(BaseModel):
    candidate_id: str
    criterion_scores: dict[str, float] = Field(default_factory=dict)
    exclusion_scores: dict[str, float] = Field(default_factory=dict)
    final_score: float = 0.0
    excluded: bool = False
    matched_branch_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""


class ResearchSelectionTrace(BaseModel):
    branch_id: str
    branch_label: str
    selected_candidate_ids: list[str] = Field(default_factory=list)
    backup_candidate_ids: list[str] = Field(default_factory=list)
    excluded_candidate_ids: list[str] = Field(default_factory=list)


class ResearchPlanRunTrace(BaseModel):
    id: str
    created_at: str
    status: Literal["completed", "awaiting_pdf_approval", "failed"] = "completed"
    topic: str = ""
    objective: str = ""
    target_count_per_branch: int = 20
    executed_queries: list[ResearchQueryTrace] = Field(default_factory=list)
    candidates: list[ResearchCandidateTrace] = Field(default_factory=list)
    screening: list[ResearchScreeningTrace] = Field(default_factory=list)
    selections: list[ResearchSelectionTrace] = Field(default_factory=list)
    selected_candidate_ids: list[str] = Field(default_factory=list)
    backup_candidate_ids: list[str] = Field(default_factory=list)
    excluded_candidate_ids: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class ResearchPlanExecuteResponse(BaseModel):
    meta: PubMedSearchMeta
    articles: list[Article]
    candidate_articles: list[Article] = Field(default_factory=list)
    run_trace: ResearchPlanRunTrace
