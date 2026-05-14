"""Research plan execution routes."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from app.schemas.project_state import ProjectQueryRecord, ProjectSearchPayload
from app.schemas.research_execution import ResearchPlanExecuteRequest, ResearchPlanExecuteResponse
from app.services.project_service import ProjectService
from app.services.research_execution_service import ResearchExecutionService

router = APIRouter(prefix="/app/projects", tags=["research-execution"])


def get_research_execution_service(request: Request) -> ResearchExecutionService:
    return request.app.state.research_execution_service


def get_project_service(request: Request) -> ProjectService:
    return request.app.state.project_service


def _persist_research_execution(project_service: ProjectService, project_id: str, response: ResearchPlanExecuteResponse) -> None:
    current_state = project_service.get_project_state(project_id)
    if current_state is None:
        return
    current_state.research_runs.insert(0, response.run_trace.model_dump(mode="json"))
    current_state.research_runs = current_state.research_runs[:20]
    full_articles = response.candidate_articles or response.articles
    if full_articles:
        timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
        query_id = f"research_{response.run_trace.id}"
        query_title = response.run_trace.topic or response.run_trace.objective or "Research plan execution"
        current_state.query_history = [
            item for item in current_state.query_history if item.id != query_id
        ]
        current_state.query_history.insert(
            0,
            ProjectQueryRecord(
                id=query_id,
                title=f"{query_title} · Agent Query",
                created_at=timestamp,
                updated_at=timestamp,
                search_payload=ProjectSearchPayload(
                    query=query_title,
                    year_start=response.run_trace.meta.get("year_start"),
                    year_end=response.run_trace.meta.get("year_end"),
                    max_results=max(1, min(5000, len(full_articles))),
                    batch_size=None,
                    min_cite=None,
                    article_type=None,
                    use_cache=True,
                    preferred_source="pubmed",
                ),
                meta=response.meta.model_copy(
                    update={
                        "fetched_results": len(full_articles),
                        "batch_size_used": len(full_articles),
                        "primary_source": "research_plan_candidates",
                    }
                ),
                articles=full_articles,
            ),
        )
        current_state.query_history = current_state.query_history[:30]
    project_service.save_project_state(project_id, current_state)


@router.post("/{project_id}/research-plan/execute", response_model=ResearchPlanExecuteResponse)
async def execute_research_plan(
    project_id: str,
    payload: ResearchPlanExecuteRequest,
    request: Request,
) -> ResearchPlanExecuteResponse:
    project_service = get_project_service(request)
    state = project_service.get_project_state(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    execution_service = get_research_execution_service(request)
    try:
        response = await execution_service.execute_plan_with_screening(
            payload.plan,
            screening_model=payload.screening_model,
            api_key=payload.api_key,
            thinking_level=payload.thinking_level,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _persist_research_execution(project_service, project_id, response)
    request.app.state.app_event_log_service.log(
        "info",
        "research_plan_executed",
        response.run_trace.topic or "Research plan executed",
        context={
            "project_id": project_id,
            "run_id": response.run_trace.id,
            "candidate_count": response.run_trace.meta.get("candidate_count"),
            "selected_count": response.run_trace.meta.get("selected_count"),
        },
    )
    return response


@router.post("/{project_id}/research-plan/execute/stream")
async def execute_research_plan_stream(
    project_id: str,
    payload: ResearchPlanExecuteRequest,
    request: Request,
) -> StreamingResponse:
    project_service = get_project_service(request)
    state = project_service.get_project_state(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    execution_service = get_research_execution_service(request)

    async def event_stream():
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

        async def progress(event: dict[str, object]) -> None:
            await queue.put({"type": "trace", **event})

        async def run_execution() -> None:
            try:
                response = await execution_service.execute_plan_with_screening(
                    payload.plan,
                    screening_model=payload.screening_model,
                    api_key=payload.api_key,
                    thinking_level=payload.thinking_level,
                    progress=progress,
                )
                _persist_research_execution(project_service, project_id, response)
                request.app.state.app_event_log_service.log(
                    "info",
                    "research_plan_executed",
                    response.run_trace.topic or "Research plan executed",
                    context={
                        "project_id": project_id,
                        "run_id": response.run_trace.id,
                        "candidate_count": response.run_trace.meta.get("candidate_count"),
                        "selected_count": response.run_trace.meta.get("selected_count"),
                    },
                )
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
