"""Application settings payloads."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AppAPIKeysPayload(BaseModel):
    assistant_api_key: str = Field(default="", max_length=4096)
    ncbi_api_key: str = Field(default="", max_length=512)
    unpaywall_email: str = Field(default="", max_length=512)
    pubmed_oa_only: bool = True
