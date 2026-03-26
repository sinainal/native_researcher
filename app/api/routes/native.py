"""Native Researcher assistant routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.schemas.helper import HelperChatRequest, HelperResetRequest
from app.services.native_researcher_service import NativeResearcherService

router = APIRouter(prefix="/native-assistant", tags=["native-assistant"])


def get_native_service(request: Request) -> NativeResearcherService:
    return request.app.state.native_helper_service


@router.post("/chat/stream")
async def native_chat_stream(payload: HelperChatRequest, request: Request) -> StreamingResponse:
    service = get_native_service(request)

    async def event_source():
        try:
            async for event in service.chat_stream(payload):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except RuntimeError as exc:
            service.log_event(
                "native_stream_error",
                thread_id=payload.thread_id,
                model=payload.model,
                message=payload.message,
                error=str(exc),
            )
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            service.log_event(
                "native_stream_error",
                thread_id=payload.thread_id,
                model=payload.model,
                message=payload.message,
                error=str(exc),
            )
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/reset")
async def native_reset(payload: HelperResetRequest, request: Request) -> dict[str, bool]:
    service = get_native_service(request)
    service.reset(payload.thread_id)
    return {"ok": True}

