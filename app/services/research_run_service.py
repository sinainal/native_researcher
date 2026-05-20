"""Project persistence and event logging for research execution runs."""

from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.project_state import ProjectQueryRecord, ProjectSearchPayload
from app.schemas.research_execution import ResearchPlanExecuteResponse
from app.services.app_event_log_service import AppEventLogService
from app.services.project_service import ProjectService


class ResearchRunService:
    """Coordinates project-state writes for completed research runs."""

    def __init__(
        self,
        *,
        project_service: ProjectService,
        event_log_service: AppEventLogService | None = None,
    ) -> None:
        self.project_service = project_service
        self.event_log_service = event_log_service

    def project_exists(self, project_id: str) -> bool:
        return self.project_service.get_project_state(project_id) is not None

    def persist_execution(self, project_id: str, response: ResearchPlanExecuteResponse) -> None:
        current_state = self.project_service.get_project_state(project_id)
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
        self.project_service.save_project_state(project_id, current_state)

    def log_execution(self, project_id: str, response: ResearchPlanExecuteResponse) -> None:
        if self.event_log_service is None:
            return
        self.event_log_service.log(
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
