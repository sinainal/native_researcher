"""Compact app event schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AppEventCreateRequest(BaseModel):
    level: str = Field(default="info", min_length=1, max_length=16)
    event: str = Field(..., min_length=1, max_length=80)
    message: str = Field(default="", max_length=240)
    context: dict[str, Any] = Field(default_factory=dict)

