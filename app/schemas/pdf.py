"""PDF resolution and download schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.article import ArticleReference
from app.schemas.pubmed import PubMedSearchMeta


class PDFCandidate(BaseModel):
    source: str
    url: str


class PDFResolveResponse(BaseModel):
    article: ArticleReference
    candidates: list[PDFCandidate]
    cache_hit: bool = False


class PDFAvailabilityRequest(BaseModel):
    articles: list[ArticleReference]


class PDFAvailabilityItem(BaseModel):
    article: ArticleReference
    ready: bool = False
    source: str | None = None
    candidate_count: int = 0
    detail: str | None = None


class PDFAvailabilityResponse(BaseModel):
    items: list[PDFAvailabilityItem]


class PDFDownloadRequest(BaseModel):
    articles: list[ArticleReference]
    download_dir: str | None = None
    max_articles: int | None = Field(default=None, ge=1)
    downloader_mode: Literal["pdf_xml", "best", "xml", "pdf", "legacy", "article_downloader", "hybrid", "final_method", "perfect"] | None = None


class PDFDownloadResult(BaseModel):
    article: ArticleReference
    success: bool
    source: str | None = None
    url: str | None = None
    file_path: str | None = None
    content_kind: str | None = None
    content_type: str | None = None
    candidate_count: int = 0
    error: str | None = None


class PDFDownloadResponse(BaseModel):
    total: int
    success_count: int
    failed_count: int
    results: list[PDFDownloadResult]


class PDFTestAttempt(BaseModel):
    source: str
    url: str
    status_code: int | None = None
    content_type: str | None = None
    mode: str | None = None
    success: bool = False
    error: str | None = None


class PDFTestResult(BaseModel):
    article: ArticleReference
    success: bool
    reason: str
    source: str | None = None
    url: str | None = None
    file_path: str | None = None
    content_kind: str | None = None
    content_type: str | None = None
    candidate_count: int = 0
    attempts: list[PDFTestAttempt] = Field(default_factory=list)


class PDFTestRequest(BaseModel):
    query: str = Field(..., min_length=1)
    year_start: int | None = Field(default=None, ge=1000, le=9999)
    year_end: int | None = Field(default=None, ge=1000, le=9999)
    max_results: int = Field(default=20, ge=1, le=100)
    batch_size: int | None = Field(default=None, ge=1, le=250)
    download_dir: str | None = None
    save_files: bool = True
    downloader_mode: Literal["pdf_xml", "best", "xml", "pdf", "legacy", "article_downloader", "hybrid", "final_method", "perfect"] | None = None


class PDFTestResponse(BaseModel):
    query: str
    pubmed_meta: PubMedSearchMeta
    total: int
    success_count: int
    failed_count: int
    success_rate: float
    reason_counts: dict[str, int]
    results: list[PDFTestResult]


class PDFFileResponse(BaseModel):
    path: str
