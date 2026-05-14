"""PDF/full-text question extraction schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.article import ArticleReference


class PDFExtractionEvidence(BaseModel):
    quote: str = ""
    page: int | None = None
    section: str = ""
    confidence: float = 0.0


class PDFExtractionAnswer(BaseModel):
    question: str
    answer: str = ""
    evidence: list[PDFExtractionEvidence] = Field(default_factory=list)
    confidence: float = 0.0


class PDFExtractionResult(BaseModel):
    article: ArticleReference
    success: bool = False
    file_path: str | None = None
    content_kind: str | None = None
    text_chars: int = 0
    answers: list[PDFExtractionAnswer] = Field(default_factory=list)
    error: str | None = None


class PDFExtractionRequest(BaseModel):
    articles: list[ArticleReference]
    questions: list[str] = Field(default_factory=list)
    extraction_fields: list[str] = Field(default_factory=list)
    model: str | None = Field(default=None, max_length=200)
    api_key: str = Field(default="", max_length=4096)
    thinking_level: str = Field(default="off", max_length=32)
    max_articles: int | None = Field(default=None, ge=1, le=50)
    download_dir: str | None = None
    downloader_mode: Literal["pdf_xml", "best", "xml", "pdf", "legacy", "article_downloader", "hybrid", "final_method", "perfect"] | None = None


class PDFExtractionResponse(BaseModel):
    total: int
    success_count: int
    failed_count: int
    questions: list[str]
    results: list[PDFExtractionResult]
    meta: dict[str, Any] = Field(default_factory=dict)
