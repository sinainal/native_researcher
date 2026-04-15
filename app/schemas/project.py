"""Project workspace schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectSummary(BaseModel):
    id: str = Field(..., min_length=1, max_length=120)
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=800)
    created_at: str = Field(..., min_length=1, max_length=64)
    updated_at: str = Field(..., min_length=1, max_length=64)
    pdf_count: int = Field(default=0, ge=0)
    note_count: int = Field(default=0, ge=0)
    project_path: str = Field(..., min_length=1)


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary] = Field(default_factory=list)


class ProjectDownloadItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=260)
    path: str = Field(..., min_length=1)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    size_bytes: int = Field(default=0, ge=0)
    modified_at: str = Field(..., min_length=1, max_length=64)
    artifact_types: list[str] = Field(default_factory=list)


class ProjectDownloadListResponse(BaseModel):
    items: list[ProjectDownloadItem] = Field(default_factory=list)


class ProjectCreateRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=800)


class ProjectUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
