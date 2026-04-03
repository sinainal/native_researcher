"""PubMed request and response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.article import ArticleReference
from app.schemas.article import Article

SearchResource = Literal["openalex", "pubmed", "europe_pmc"]


class PubMedSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    year_start: int | None = Field(default=None, ge=1000, le=9999)
    year_end: int | None = Field(default=None, ge=1000, le=9999)
    max_results: int = Field(default=20, ge=1, le=5000)
    batch_size: int | None = Field(default=None, ge=1, le=500)
    min_cite: int | None = Field(default=None, ge=0, le=1000000)
    article_type: str | None = Field(default=None, min_length=1, max_length=200)
    use_cache: bool = True
    preferred_source: SearchResource = "openalex"

    @model_validator(mode="after")
    def validate_year_range(self) -> "PubMedSearchRequest":
        if (
            self.year_start is not None
            and self.year_end is not None
            and self.year_start > self.year_end
        ):
            raise ValueError("year_start cannot be greater than year_end")
        return self


class PubMedSearchMeta(BaseModel):
    full_query: str
    total_results_found: int
    fetched_results: int
    batch_size_used: int
    request_count: int
    elapsed_ms: int
    cache_hit: bool
    oa_only: bool = False
    primary_source: str | None = None
    sources_used: list[str] = Field(default_factory=list)
    fallback_used: bool = False


class PubMedSearchResponse(BaseModel):
    meta: PubMedSearchMeta
    articles: list[Article]


class PubMedCitationRequest(BaseModel):
    articles: list[ArticleReference]


class PubMedCitationItem(BaseModel):
    pmid: str | None = None
    doi: str | None = None
    citation_count: int | None = None


class PubMedCitationResponse(BaseModel):
    items: list[PubMedCitationItem]
