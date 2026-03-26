"""Project workspace routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.schemas.project import (
    ProjectCreateRequest,
    ProjectDownloadListResponse,
    ProjectListResponse,
    ProjectSummary,
    ProjectUpdateRequest,
)
from app.services.project_service import ProjectService

router = APIRouter(prefix="/app/projects", tags=["projects"])


def get_project_service(request: Request) -> ProjectService:
    settings = request.app.state.settings
    return ProjectService(settings.workspace_root)


def log_project_event(request: Request, level: str, event: str, message: str, **context: object) -> None:
    request.app.state.app_event_log_service.log(level, event, message, context=context)


@router.get("", response_model=ProjectListResponse)
async def list_projects(request: Request) -> ProjectListResponse:
    service = get_project_service(request)
    return ProjectListResponse(projects=service.list_projects())


@router.post("", response_model=ProjectSummary)
async def create_project(payload: ProjectCreateRequest, request: Request) -> ProjectSummary:
    service = get_project_service(request)
    project = service.create_project(payload)
    log_project_event(
        request,
        "info",
        "project_created",
        project.name,
        project_id=project.id,
    )
    return project


@router.get("/{project_id}", response_model=ProjectSummary)
async def get_project(project_id: str, request: Request) -> ProjectSummary:
    service = get_project_service(request)
    project = service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


@router.get("/{project_id}/downloads", response_model=ProjectDownloadListResponse)
async def list_project_downloads(project_id: str, request: Request) -> ProjectDownloadListResponse:
    service = get_project_service(request)
    items = service.list_project_downloads(project_id)
    if items is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return ProjectDownloadListResponse(items=items)


@router.post("/{project_id}/touch", response_model=ProjectSummary)
async def touch_project(project_id: str, request: Request) -> ProjectSummary:
    service = get_project_service(request)
    project = service.touch_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


@router.patch("/{project_id}", response_model=ProjectSummary)
async def update_project(project_id: str, payload: ProjectUpdateRequest, request: Request) -> ProjectSummary:
    next_name = payload.name.strip()
    if not next_name:
        raise HTTPException(status_code=422, detail="Project name cannot be empty.")
    service = get_project_service(request)
    project = service.update_project(project_id, ProjectUpdateRequest(name=next_name))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    log_project_event(
        request,
        "info",
        "project_renamed",
        project.name,
        project_id=project.id,
    )
    return project
