"""Compact app event routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas.app_event import AppEventCreateRequest
from app.services.app_event_log_service import AppEventLogService

router = APIRouter(prefix="/app/events", tags=["app-events"])


def get_event_log_service(request: Request) -> AppEventLogService:
    return request.app.state.app_event_log_service


@router.post("")
async def create_event(payload: AppEventCreateRequest, request: Request) -> dict[str, bool]:
    service = get_event_log_service(request)
    service.log(
        payload.level,
        payload.event,
        payload.message,
        context=payload.context,
    )
    return {"ok": True}
