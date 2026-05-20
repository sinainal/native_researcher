"""Research plan execution routes."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from app.schemas.research_execution import ResearchPlanExecuteRequest, ResearchPlanExecuteResponse
from app.services.pdf_extraction_service import PDFExtractionService
from app.services.research_execution_service import ResearchExecutionService
from app.services.research_pdf_pipeline_service import ResearchPdfPipelineService
from app.services.research_plan_payload_service import build_execution_plan
from app.services.research_run_service import ResearchRunService

router = APIRouter(prefix="/app/projects", tags=["research-execution"])


def get_research_execution_service(request: Request) -> ResearchExecutionService:
    return request.app.state.research_execution_service


def get_research_run_service(request: Request) -> ResearchRunService:
    service = getattr(request.app.state, "research_run_service", None)
    if service is not None:
        return service
    return ResearchRunService(
        project_service=request.app.state.project_service,
        event_log_service=getattr(request.app.state, "app_event_log_service", None),
    )


def get_pdf_extraction_service(request: Request) -> PDFExtractionService:
    return PDFExtractionService(
        pdf_service=request.app.state.pdf_service,
        settings=getattr(request.app.state, "settings", None),
    )


def get_research_pdf_pipeline_service(request: Request) -> ResearchPdfPipelineService:
    return ResearchPdfPipelineService(extraction_service=get_pdf_extraction_service(request))


@router.post("/{project_id}/research-plan/execute", response_model=ResearchPlanExecuteResponse)
async def execute_research_plan(
    project_id: str,
    payload: ResearchPlanExecuteRequest,
    request: Request,
) -> ResearchPlanExecuteResponse:
    run_service = get_research_run_service(request)
    if not run_service.project_exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")

    execution_service = get_research_execution_service(request)
    pdf_pipeline_service = get_research_pdf_pipeline_service(request)
    try:
        plan = build_execution_plan(payload)
        response = await execution_service.execute_plan_with_screening(
            plan,
            screening_model=payload.screening_model,
            api_key=payload.api_key,
            thinking_level=payload.thinking_level,
        )
        if payload.pdf_extractor_enabled and not payload.autoprocess:
            pdf_pipeline_service.defer_pdf_screening(payload, plan, response)
        else:
            await pdf_pipeline_service.run_pdf_screening(payload, plan, response)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    run_service.persist_execution(project_id, response)
    run_service.log_execution(project_id, response)
    return response


@router.post("/{project_id}/research-plan/execute/stream")
async def execute_research_plan_stream(
    project_id: str,
    payload: ResearchPlanExecuteRequest,
    request: Request,
) -> StreamingResponse:
    run_service = get_research_run_service(request)
    if not run_service.project_exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")

    execution_service = get_research_execution_service(request)
    pdf_pipeline_service = get_research_pdf_pipeline_service(request)

    async def event_stream():
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

        async def progress(event: dict[str, object]) -> None:
            await queue.put({"type": "trace", **event})

        async def run_execution() -> None:
            try:
                plan = build_execution_plan(payload)
                response = await execution_service.execute_plan_with_screening(
                    plan,
                    screening_model=payload.screening_model,
                    api_key=payload.api_key,
                    thinking_level=payload.thinking_level,
                    progress=progress,
                )
                if payload.pdf_extractor_enabled and not payload.autoprocess:
                    pdf_pipeline_service.defer_pdf_screening(payload, plan, response)
                    await progress(
                        {
                            "stage": "pdf_screening_awaiting_approval",
                            "message": "PDF/full-text screening is waiting for manual approval.",
                            "pdf_scope": payload.pdf_scope,
                        }
                    )
                else:
                    await pdf_pipeline_service.run_pdf_screening(payload, plan, response, progress=progress)
                run_service.persist_execution(project_id, response)
                run_service.log_execution(project_id, response)
                await queue.put({"type": "final", "response": response.model_dump(mode="json")})
            except Exception as exc:
                await queue.put({"type": "error", "message": str(exc)})
            finally:
                await queue.put({"type": "done"})

        task = asyncio.create_task(run_execution())
        try:
            while True:
                event = await queue.get()
                if event.get("type") == "done":
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
