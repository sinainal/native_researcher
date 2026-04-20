"""Application settings payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SearchResource = Literal["openalex", "pubmed", "europe_pmc", "pmc", "core", "arxiv"]
PDFDownloaderMode = Literal["pdf_xml", "best", "xml", "pdf", "legacy", "article_downloader", "hybrid", "final_method", "perfect"]


class AppAPIKeysPayload(BaseModel):
    assistant_api_key: str = Field(default="", max_length=4096)
    ncbi_api_key: str = Field(default="", max_length=512)
    unpaywall_email: str = Field(default="", max_length=512)
    openalex_api_key: str = Field(default="", max_length=512)
    core_api_key: str = Field(default="", max_length=512)
    pubmed_oa_only: bool = True
    ai_primary_search_resource: SearchResource = "pubmed"
    pdf_downloader_mode: PDFDownloaderMode = "pdf_xml"
    pdf_unpaywall_fallback_enabled: bool = True
    pdf_core_fallback_enabled: bool = False
    pdf_arxiv_fallback_enabled: bool = False


class OllamaSettingsPayload(BaseModel):
    ollama_base_url: str = Field(default="http://localhost:11434", max_length=1024)
    ollama_model: str = Field(default="", max_length=256)
    ollama_thinking_level: str = Field(default="off", max_length=16)
    warmup: bool = False


class OllamaModelInfo(BaseModel):
    name: str
    size: int | None = None
    modified_at: str | None = None
    digest: str | None = None


class OllamaStatusResponse(BaseModel):
    ollama_base_url: str
    connected: bool
    version: str | None = None
    ollama_model: str = ""
    ollama_thinking_level: str = "off"
    models: list[OllamaModelInfo] = Field(default_factory=list)
    error: str | None = None
    warmup_error: str | None = None
    warming_up: bool = False
    warming_model: str | None = None
