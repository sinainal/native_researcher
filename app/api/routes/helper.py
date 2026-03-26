"""Helper AI routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.schemas.helper import HelperChatRequest, HelperChatResponse, HelperResetRequest
from app.services.helper_ai_service import HelperAIService

router = APIRouter(prefix="/assistant", tags=["assistant"])


def get_helper_service(request: Request) -> HelperAIService:
    return request.app.state.helper_service


@router.post("/chat", response_model=HelperChatResponse)
async def helper_chat(payload: HelperChatRequest, request: Request) -> HelperChatResponse:
    service = get_helper_service(request)
    try:
        return await service.chat(payload)
    except RuntimeError as exc:
        service.log_event(
            "assistant_chat_error",
            thread_id=payload.thread_id,
            mode=payload.mode,
            model=payload.model,
            message=payload.message,
            error=str(exc),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        service.log_event(
            "assistant_chat_error",
            thread_id=payload.thread_id,
            mode=payload.mode,
            model=payload.model,
            message=payload.message,
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/chat/stream")
async def helper_chat_stream(payload: HelperChatRequest, request: Request) -> StreamingResponse:
    service = get_helper_service(request)

    async def event_source():
        try:
            async for event in service.chat_stream(payload):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except RuntimeError as exc:
            service.log_event(
                "assistant_stream_error",
                thread_id=payload.thread_id,
                mode=payload.mode,
                model=payload.model,
                message=payload.message,
                error=str(exc),
            )
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            service.log_event(
                "assistant_stream_error",
                thread_id=payload.thread_id,
                mode=payload.mode,
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
async def helper_reset(payload: HelperResetRequest, request: Request) -> dict[str, bool]:
    service = get_helper_service(request)
    service.reset(payload.thread_id)
    return {"ok": True}


@router.get("/history")
async def helper_history(request: Request, limit: int = 100) -> dict[str, object]:
    service = get_helper_service(request)
    entries = service.recent_logs(limit=limit)
    return {"items": entries, "count": len(entries)}
