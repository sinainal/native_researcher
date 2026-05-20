"""Helpers for turning research execution requests into runtime plans."""

from __future__ import annotations

from app.schemas.research_execution import ResearchPlanExecuteRequest


def build_execution_plan(payload: ResearchPlanExecuteRequest) -> dict:
    """Return the executable plan used by the research execution pipeline."""
    plan = dict(payload.plan)
    if not payload.criteria_enabled:
        plan["criteria_mode"] = "disabled"
        plan["screening_criteria"] = []
        plan["exclusion_criteria"] = []
    plan["full_text_settings"] = {
        "pdf_extractor_enabled": bool(payload.pdf_extractor_enabled),
        "autoprocess": bool(payload.autoprocess),
        "pdf_scope": payload.pdf_scope,
        "full_text_model": full_text_model_from_payload(payload) or "",
    }
    return plan


def full_text_model_from_payload(payload: ResearchPlanExecuteRequest) -> str | None:
    if payload.full_text_model is not None:
        return payload.full_text_model
    return payload.screening_model
