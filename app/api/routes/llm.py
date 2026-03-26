"""Batch LLM analysis routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.schemas.llm import LLMProcessRequest, LLMProcessResponse
from app.services.batch_llm_service import BatchLLMService

router = APIRouter(prefix="/llm", tags=["llm"])


def get_batch_llm_service(request: Request) -> BatchLLMService:
    return request.app.state.batch_llm_service


@router.post("/process", response_model=LLMProcessResponse)
async def process_articles(
    payload: LLMProcessRequest,
    request: Request,
) -> LLMProcessResponse:
    service = get_batch_llm_service(request)
    try:
        return await service.process(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
