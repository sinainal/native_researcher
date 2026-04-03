"""Application settings payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SearchResource = Literal["openalex", "pubmed", "europe_pmc"]


class AppAPIKeysPayload(BaseModel):
    assistant_api_key: str = Field(default="", max_length=4096)
    ncbi_api_key: str = Field(default="", max_length=512)
    unpaywall_email: str = Field(default="", max_length=512)
    pubmed_oa_only: bool = True
    ai_primary_search_resource: SearchResource = "openalex"
