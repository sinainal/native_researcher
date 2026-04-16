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
