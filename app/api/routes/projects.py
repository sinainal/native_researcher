"""Project workspace routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas.project import ProjectCreateRequest, ProjectListResponse, ProjectSummary
from app.services.project_service import ProjectService

router = APIRouter(prefix="/app/projects", tags=["projects"])


def get_project_service(request: Request) -> ProjectService:
    settings = request.app.state.settings
    return ProjectService(settings.workspace_root)


@router.get("", response_model=ProjectListResponse)
async def list_projects(request: Request) -> ProjectListResponse:
    service = get_project_service(request)
    return ProjectListResponse(projects=service.list_projects())


@router.post("", response_model=ProjectSummary)
async def create_project(payload: ProjectCreateRequest, request: Request) -> ProjectSummary:
    service = get_project_service(request)
    return service.create_project(payload)
