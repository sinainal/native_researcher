"""Screen normalized research candidates with plan criteria."""

from __future__ import annotations

import asyncio
import json
import math
import re
from typing import Any
from collections.abc import Awaitable, Callable

from app.genai import create_genai_client, load_genai_sdk
from app.llm import extract_ollama_tool_calls, llamacpp_chat_stream, ollama_chat_stream, resolve_chat_model_target
from app.schemas.article import Article
from app.schemas.research_execution import ResearchScreeningTrace
from app.services.batch_llm_service import parse_json_list
from app.services.research_candidate_normalizer import NormalizedResearchCandidate

DETERMINISTIC_SCREENING_MODEL = "__deterministic__"
BATCH_SIZE = 1
MAX_ABSTRACT_CHARS = 2200
OLLAMA_FIRST_TOKEN_SECONDS = 20.0
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "with",
    "without",
    "paper",
    "papers",
    "research",
    "study",
    "studies",
    "must",
    "should",
    "score",
    "specific",
    "explicit",
}


class ResearchScreeningService:
    """Screening subagent that scores candidate abstracts against a plan."""

    def __init__(self, *, settings: Any | None = None) -> None:
        self.settings = settings

    async def screen_candidates(
        self,
        candidates: list[NormalizedResearchCandidate],
        plan: dict[str, Any],
        *,
        model: str | None = None,
        api_key: str = "",
        thinking_level: str = "off",
        progress: ProgressCallback | None = None,
    ) -> list[ResearchScreeningTrace]:
        if not candidates:
            return []
        if str(model or "").strip() == DETERMINISTIC_SCREENING_MODEL:
            return self._screen_candidates_deterministic(candidates, plan)
        model_target = resolve_chat_model_target(model, settings=self.settings)
        traces: list[ResearchScreeningTrace] = []
        for start in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[start:start + BATCH_SIZE]
            if progress is not None:
                await progress(
                    {
                        "stage": "screening_batch",
                        "message": f"Screening candidates {start + 1}-{start + len(batch)} of {len(candidates)}.",
                        "batch_index": start // BATCH_SIZE + 1,
                        "batch_count": math.ceil(len(candidates) / BATCH_SIZE),
                        "candidate_count": len(batch),
                    }
                )
            items = await self._run_agent_batch(
                batch,
                plan,
                model_target=model_target,
                api_key=api_key,
                thinking_level=thinking_level,
                progress=progress,
            )
            traces.extend(self._normalize_agent_items(batch, plan, items))
        return traces

    def _screen_candidates_deterministic(
        self,
        candidates: list[NormalizedResearchCandidate],
        plan: dict[str, Any],
    ) -> list[ResearchScreeningTrace]:
        criteria = _criteria(plan)
        exclusions = [str(item).strip() for item in plan.get("exclusion_criteria") or [] if str(item).strip()]
        traces: list[ResearchScreeningTrace] = []
        for candidate in candidates:
            text = _article_text(candidate.article)
            criterion_scores = {
                criterion["id"]: _keyword_score(text, criterion["terms"])
                for criterion in criteria
            }
            exclusion_scores = {
                _exclusion_id(index): _exclusion_score(text, exclusion)
                for index, exclusion in enumerate(exclusions, start=1)
            }
            excluded = any(score >= 0.75 for score in exclusion_scores.values())
            traces.append(
                ResearchScreeningTrace(
                    candidate_id=candidate.candidate_id,
                    criterion_scores=criterion_scores,
                    exclusion_scores=exclusion_scores,
                    final_score=_weighted_squared_score(criterion_scores, criteria),
                    excluded=excluded,
                    matched_branch_ids=sorted({match.branch_id for match in candidate.matches if match.branch_id}),
                    evidence=_evidence(candidate.article, criterion_scores, exclusion_scores),
                    rationale="Deterministic local scorer used for tests or explicit offline execution.",
                )
            )
        return traces

    async def _run_agent_batch(
        self,
        candidates: list[NormalizedResearchCandidate],
        plan: dict[str, Any],
        *,
        model_target: Any,
        api_key: str,
        thinking_level: str,
        progress: ProgressCallback | None,
    ) -> list[Any]:
        system_instruction = (
            "screening subagent: screen the provided literature candidate batch. "
            "Use only the provided candidates and criteria. "
            "Call `screen_research_candidates` exactly once. "
            "No prose."
        )
        criteria_payload = [
            {
                "id": criterion["id"],
                "label": criterion["label"],
                "weight": criterion["weight"],
            }
            for criterion in _criteria(plan)
        ]
        user_prompt = json.dumps(
            {
                "task": "Score each candidate. Return exactly one item per provided candidate_id.",
                "score_rules": {
                    "s": "criterion scores keyed by criterion id: 0 absent, 0.5 partial, 1 explicit",
                    "x": "1 if excluded by exclusion criteria, otherwise 0",
                    "e": "up to 2 short evidence strings from title/abstract",
                },
                "plan": {
                    "topic": plan.get("topic") or "",
                    "objective": plan.get("objective") or "",
                    "criteria": criteria_payload,
                    "exclusion_criteria": plan.get("exclusion_criteria") or [],
                },
                "preferred_output_shape": {
                    "id": "cand_1",
                    "s": {"criterion_id": 0.0},
                    "x": 0,
                    "e": ["short evidence"],
                },
                "candidates": [_candidate_payload(candidate) for candidate in candidates],
            },
            ensure_ascii=False,
        )
        if model_target.provider in {"ollama", "llamacpp"}:
            return await self._run_ollama_agent_batch_stream(
                model_name=model_target.model_name,
                provider=model_target.provider,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt},
                ],
                tools=self._build_ollama_screening_toolset(),
                thinking_level=thinking_level,
                progress=progress,
                format_retries=2,
            )

        if len((api_key or "").strip()) < 10:
            raise RuntimeError("Screening agent requires a Gemini API key for Gemini models.")
        _genai, types = load_genai_sdk()
        client = create_genai_client(api_key)

        def _generate() -> str:
            response = client.models.generate_content(
                model=model_target.model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                ),
            )
            return str(getattr(response, "text", None) or "").strip()

        return _parse_agent_json_list(await asyncio.to_thread(_generate))

    async def _run_ollama_agent_batch_stream(
        self,
        *,
        model_name: str,
        provider: str = "ollama",
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        thinking_level: str,
        progress: ProgressCallback | None,
        format_retries: int = 0,
    ) -> list[Any]:
        if progress is not None:
            await progress(
                {
                    "stage": "screening_agent_request",
                    "message": f"Starting screening agent on {provider} model {model_name}.",
                    "model": model_name,
                }
            )
        stream_factory = llamacpp_chat_stream if provider == "llamacpp" else ollama_chat_stream
        stream = stream_factory(
            base_url=self._local_llm_base_url(provider),
            model=model_name,
            messages=messages,
            tools=tools,
            thinking_level=thinking_level,
            **(
                {
                    "tool_choice": {
                        "type": "function",
                        "function": {"name": "screen_research_candidates"},
                    }
                }
                if provider == "llamacpp"
                else {}
            ),
            timeout_seconds=600.0,
            request_user_agent=self._request_user_agent(),
        ).__aiter__()
        content_parts: list[str] = []
        tool_items: list[Any] | None = None
        format_errors: list[str] = []
        first_text_seen = False
        first_kind = ""
        while not first_text_seen:
            try:
                chunk = await asyncio.wait_for(anext(stream), timeout=OLLAMA_FIRST_TOKEN_SECONDS)
            except StopAsyncIteration as exc:
                raise RuntimeError("Screening agent finished without emitting any content.") from exc
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    "Screening agent did not emit a thinking/content/tool token within 20 seconds; "
                    "Ollama did not start producing output."
                ) from exc
            calls = extract_ollama_tool_calls(chunk.get("message") or {})
            if calls:
                try:
                    tool_items = _tool_call_screening_items(calls[0].args)
                except RuntimeError as error:
                    format_errors.append(str(error))
                    tool_items = None
                first_text_seen = True
                first_kind = "tool" if tool_items is not None else "tool_format_error"
                if progress is not None:
                    if tool_items is None:
                        await progress(
                            {
                                "stage": "screening_agent_format_error",
                                "message": f"Screening agent function call had invalid arguments: {format_errors[-1]}",
                                "kind": first_kind,
                                "model": model_name,
                            }
                        )
                        break
                    await progress(
                        {
                            "stage": "screening_agent_first_token",
                            "message": f"Screening agent function call received with {len(tool_items)} scored candidates.",
                            "kind": "tool",
                            "model": model_name,
                        }
                    )
                break
            thinking, content = _ollama_chunk_text(chunk)
            if content:
                content_parts.append(content)
            if thinking or content:
                first_text_seen = True
                first_kind = "thinking" if thinking else "content"
                if progress is not None:
                    preview = _truncate(thinking or content, 220)
                    await progress(
                        {
                            "stage": "screening_agent_first_token",
                            "message": f"Screening agent first {first_kind} token received: {preview}",
                            "kind": first_kind,
                            "model": model_name,
                        }
                    )

        async for chunk in stream:
            calls = extract_ollama_tool_calls(chunk.get("message") or {})
            if calls and tool_items is None:
                try:
                    tool_items = _tool_call_screening_items(calls[0].args)
                except RuntimeError as error:
                    format_errors.append(str(error))
                    tool_items = None
                    if progress is not None:
                        await progress(
                            {
                                "stage": "screening_agent_format_error",
                                "message": f"Screening agent function call had invalid arguments: {error}",
                                "model": model_name,
                            }
                        )
                    continue
                if progress is not None:
                    await progress(
                        {
                            "stage": "screening_agent_tool_call",
                            "message": f"Screening agent function call received with {len(tool_items)} scored candidates.",
                            "candidate_count": len(tool_items),
                            "model": model_name,
                        }
                    )
            thinking, content = _ollama_chunk_text(chunk)
            if content:
                content_parts.append(content)

        if tool_items is not None:
            return tool_items
        if content_parts:
            parsed_items = _parse_screening_text_items("".join(content_parts))
            if parsed_items is not None:
                if progress is not None:
                    await progress(
                        {
                            "stage": "screening_agent_text_json",
                            "message": "Screening agent returned JSON text instead of a function call; parsed it without failing the run.",
                            "candidate_count": len(parsed_items),
                            "model": model_name,
                        }
                    )
                return parsed_items
        if format_errors and format_retries > 0:
            if progress is not None:
                await progress(
                    {
                        "stage": "screening_agent_format_retry",
                        "message": "Screening agent used the wrong function-call argument shape. Asking it to call the function again with an items list.",
                        "model": model_name,
                    }
                )
            return await self._run_ollama_agent_batch_stream(
                model_name=model_name,
                provider=provider,
                messages=[
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "Your previous `screen_research_candidates` function call had invalid arguments. "
                            "Call `screen_research_candidates` again now with exactly this argument shape: "
                            '{"items":[{"id":"cand_1","s":{"criterion_id":0.0},"x":0,'
                            '"e":["short evidence from the abstract"]}]}. '
                            "Include exactly one item for the provided candidate_id. Do not answer in prose."
                        ),
                    },
                ],
                tools=tools,
                thinking_level=thinking_level,
                progress=progress,
                format_retries=format_retries - 1,
            )
        if format_errors:
            raise RuntimeError(format_errors[-1])
        if content_parts:
            if format_retries > 0:
                preview = _truncate("".join(content_parts).strip(), 500)
                if progress is not None:
                    await progress(
                        {
                            "stage": "screening_agent_format_retry",
                            "message": "Screening agent returned text instead of a function call. Sending feedback and retrying the tool call.",
                            "model": model_name,
                        }
                    )
                return await self._run_ollama_agent_batch_stream(
                    model_name=model_name,
                    provider=provider,
                    messages=[
                        *messages,
                        {
                            "role": "assistant",
                            "content": preview,
                        },
                        {
                            "role": "user",
                            "content": (
                                "You returned text/JSON instead of calling the required function. "
                                "Do not write JSON in the message content. "
                                "Call `screen_research_candidates` now with exactly this argument shape: "
                                '{"items":[{"id":"cand_1","s":{"criterion_id":0.0},"x":0,'
                                '"e":["short evidence from the abstract"]}]}. '
                                "Include exactly one item for the provided candidate_id."
                            ),
                        },
                    ],
                    tools=tools,
                    thinking_level=thinking_level,
                    progress=progress,
                    format_retries=format_retries - 1,
                )
            raise RuntimeError(
                "Screening agent returned prose/JSON text instead of calling `screen_research_candidates` after retry."
            )
        if format_retries > 0:
            if progress is not None:
                await progress(
                    {
                        "stage": "screening_agent_format_retry",
                        "message": "Screening agent returned no valid tool call or parseable JSON. Sending error feedback and retrying the tool call.",
                        "model": model_name,
                    }
                )
            return await self._run_ollama_agent_batch_stream(
                model_name=model_name,
                provider=provider,
                messages=[
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "Error: your previous response did not call `screen_research_candidates` "
                            "and did not contain parseable screening JSON. Retry now. "
                            "Call `screen_research_candidates` with exactly this argument shape: "
                            '{"items":[{"id":"cand_1","s":{"criterion_id":0.0},"x":0,'
                            '"e":["short evidence from the abstract"]}]}. '
                            "Include exactly one item for the provided candidate_id. Do not answer in prose."
                        ),
                    },
                ],
                tools=tools,
                thinking_level=thinking_level,
                progress=progress,
                format_retries=format_retries - 1,
            )
        raise RuntimeError("Screening agent did not call `screen_research_candidates`.")

    def _build_ollama_screening_toolset(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "screen_research_candidates",
                    "description": "Return structured screening scores for the single provided research candidate.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "candidate_id": {"type": "string"},
                                        "id": {"type": "string"},
                                        "criterion_scores": {
                                            "type": "object",
                                            "additionalProperties": {"type": "number"},
                                        },
                                        "s": {
                                            "type": "object",
                                            "additionalProperties": {"type": "number"},
                                        },
                                        "exclusion_scores": {
                                            "type": "object",
                                            "additionalProperties": {"type": "number"},
                                        },
                                        "x": {"type": "number"},
                                        "confidence": {"type": "number"},
                                        "evidence": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "e": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "rationale": {"type": "string"},
                                        "r": {"type": "string"},
                                    },
                                },
                            }
                        },
                        "required": ["items"],
                    },
                },
            }
        ]


    def _normalize_agent_items(
        self,
        candidates: list[NormalizedResearchCandidate],
        plan: dict[str, Any],
        items: list[Any],
    ) -> list[ResearchScreeningTrace]:
        criteria = _criteria(plan)
        exclusions = [str(item).strip() for item in plan.get("exclusion_criteria") or [] if str(item).strip()]
        criterion_aliases = _criterion_aliases(criteria)
        item_by_id = {
            str(item.get("candidate_id") or item.get("id") or ""): item
            for item in items
            if isinstance(item, dict)
        }
        traces: list[ResearchScreeningTrace] = []
        for candidate in candidates:
            item = item_by_id.get(candidate.candidate_id)
            if item is None:
                text = _article_text(candidate.article)
                criterion_scores = {
                    criterion["id"]: _keyword_score(text, criterion["terms"])
                    for criterion in criteria
                }
                exclusion_scores = {
                    _exclusion_id(index): _exclusion_score(text, exclusion)
                    for index, exclusion in enumerate(exclusions, start=1)
                }
                traces.append(
                    ResearchScreeningTrace(
                        candidate_id=candidate.candidate_id,
                        criterion_scores=criterion_scores,
                        exclusion_scores=exclusion_scores,
                        final_score=_weighted_squared_score(criterion_scores, criteria),
                        excluded=any(score >= 0.75 for score in exclusion_scores.values()),
                        matched_branch_ids=sorted({match.branch_id for match in candidate.matches if match.branch_id}),
                        evidence=["Screening agent omitted this candidate; local scorer completed the record."],
                        rationale="Completed missing candidate score locally to keep the execution trace intact.",
                    )
                )
                continue
            raw_criterion_scores = (
                item.get("criterion_scores")
                or item.get("criteria_scores")
                or item.get("scores")
                or item.get("s")
                or {}
            )
            criterion_scores = _normalize_criterion_scores(
                raw_criterion_scores,
                criteria,
                criterion_aliases,
            )
            exclusion_scores = _normalize_exclusion_scores(item, exclusions)
            explicit_excluded = _clamp_score(item.get("x", item.get("excluded", item.get("exclude", 0)))) >= 0.75
            excluded = explicit_excluded or any(score >= 0.75 for score in exclusion_scores.values())
            traces.append(
                ResearchScreeningTrace(
                    candidate_id=candidate.candidate_id,
                    criterion_scores=criterion_scores,
                    exclusion_scores=exclusion_scores,
                    final_score=_weighted_squared_score(criterion_scores, criteria),
                    excluded=excluded,
                    matched_branch_ids=sorted({match.branch_id for match in candidate.matches if match.branch_id}),
                    evidence=[
                        str(value)[:500]
                        for value in (item.get("evidence") or item.get("e") or [])
                        if str(value).strip()
                    ][:5],
                    rationale=str(item.get("rationale") or item.get("r") or "").strip()[:1000],
                )
            )
        return traces

    def _ollama_base_url(self) -> str:
        return str(getattr(self.settings, "ollama_base_url", "http://localhost:11434") or "http://localhost:11434")

    def _local_llm_base_url(self, provider: str) -> str:
        if provider == "llamacpp":
            return str(getattr(self.settings, "llamacpp_base_url", "http://localhost:8098") or "http://localhost:8098")
        return self._ollama_base_url()

    def _request_user_agent(self) -> str:
        return str(getattr(self.settings, "request_user_agent", "NativeResearcher/0.1") or "NativeResearcher/0.1")


def _criteria(plan: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = plan.get("screening_criteria") or []
    criteria: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("id") or f"Criterion {index}").strip()
        criterion_id = str(item.get("id") or _slug(label) or f"criterion_{index}").strip()
        text = " ".join(
            str(item.get(key) or "")
            for key in ("label", "description", "scoring_guidance")
        )
        terms = _terms(text)
        if not terms:
            terms = _terms(label)
        try:
            weight = float(item.get("weight", 1) or 1)
        except (TypeError, ValueError):
            weight = 1.0
        criteria.append(
            {
                "id": criterion_id,
                "label": label,
                "terms": terms,
                "weight": max(0.0, weight),
            }
        )
    if criteria:
        return criteria
    return [
        {
            "id": "topic_relevance",
            "label": "Topic relevance",
            "terms": _terms(" ".join(str(plan.get(key) or "") for key in ("topic", "objective"))),
            "weight": 1.0,
        }
    ]


def _article_text(article: Article) -> str:
    return " ".join(
        [
            article.title or "",
            article.abstract or "",
            article.journal or "",
            " ".join(article.keywords or []),
            " ".join(article.mesh_terms or []),
            " ".join(article.article_types or []),
        ]
    ).lower()


def _terms(value: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", value.lower())
    seen: set[str] = set()
    terms: list[str] = []
    for word in words:
        normalized = word.strip("-")
        if normalized in _STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return terms[:32]


def _score_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _criterion_aliases(criteria: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for criterion in criteria:
        criterion_id = str(criterion.get("id") or "")
        label = str(criterion.get("label") or "")
        aliases[_score_key(criterion_id)] = criterion_id
        aliases[_score_key(label)] = criterion_id
        aliases[_score_key(criterion_id.replace("_", " "))] = criterion_id
        aliases[_score_key(label.replace("_", " "))] = criterion_id
    return {key: value for key, value in aliases.items() if key and value}


def _normalize_criterion_scores(
    raw_scores: Any,
    criteria: list[dict[str, Any]],
    aliases: dict[str, str],
) -> dict[str, float]:
    normalized = {str(criterion["id"]): 0.0 for criterion in criteria}
    if not isinstance(raw_scores, dict):
        return normalized
    for raw_key, raw_value in raw_scores.items():
        key = aliases.get(_score_key(str(raw_key)))
        if key is None:
            continue
        normalized[key] = max(normalized.get(key, 0.0), _clamp_score(raw_value))
    if len(criteria) == 1 and not any(normalized.values()):
        for fallback_key in ("score", "relevance", "confidence", "overall", "final_score"):
            if fallback_key in raw_scores:
                normalized[str(criteria[0]["id"])] = _clamp_score(raw_scores[fallback_key])
                break
    return normalized


def _normalize_exclusion_scores(item: dict[str, Any], exclusions: list[str]) -> dict[str, float]:
    raw_scores = item.get("exclusion_scores") or item.get("x_scores") or {}
    normalized = {
        _exclusion_id(index): 0.0
        for index, _exclusion in enumerate(exclusions, start=1)
    }
    if isinstance(raw_scores, dict):
        for exclusion_id in normalized:
            normalized[exclusion_id] = _clamp_score(raw_scores.get(exclusion_id, 0))
    compact_excluded = _clamp_score(item.get("x", item.get("excluded", item.get("exclude", 0)))) >= 0.75
    if compact_excluded and normalized:
        first_key = next(iter(normalized))
        normalized[first_key] = 1.0
    return normalized


def _keyword_score(text: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    hits = sum(1 for term in terms if term in text)
    if hits <= 0:
        return 0.0
    return min(1.0, math.sqrt(hits / max(1, min(len(terms), 12))))


def _exclusion_score(text: str, exclusion: str) -> float:
    terms = _terms(exclusion)
    if not terms:
        return 0.0
    hits = sum(1 for term in terms if term in text)
    if hits >= max(1, min(3, len(terms))):
        return 1.0
    if hits:
        return min(0.5, hits / max(2, len(terms)))
    return 0.0


def _weighted_squared_score(scores: dict[str, float], criteria: list[dict[str, Any]]) -> float:
    denominator = sum(float(item["weight"]) ** 2 for item in criteria)
    if denominator <= 0:
        return 0.0
    numerator = sum((scores.get(item["id"], 0.0) * float(item["weight"])) ** 2 for item in criteria)
    return round(max(0.0, min(1.0, numerator / denominator)), 4)


def _evidence(
    article: Article,
    criterion_scores: dict[str, float],
    exclusion_scores: dict[str, float],
) -> list[str]:
    evidence = []
    if article.abstract:
        evidence.append("Abstract available")
    if article.keywords:
        evidence.append("Keywords available")
    if article.mesh_terms:
        evidence.append("MeSH terms available")
    if any(score >= 0.75 for score in exclusion_scores.values()):
        evidence.append("Exclusion criterion matched")
    if any(score > 0 for score in criterion_scores.values()):
        evidence.append("Plan criterion terms matched")
    return evidence[:5]


def _exclusion_id(index: int) -> str:
    return f"exclusion_{index}"


def _candidate_payload(candidate: NormalizedResearchCandidate) -> dict[str, Any]:
    article = candidate.article
    return {
        "candidate_id": candidate.candidate_id,
        "title": article.title,
        "abstract": _truncate(article.abstract, MAX_ABSTRACT_CHARS),
        "year": article.year,
        "journal": article.journal,
        "article_type": article.article_type,
        "keywords": article.keywords,
        "mesh_terms": article.mesh_terms,
        "doi": article.doi,
        "pmid": article.pmid,
        "pmc_id": article.pmc_id,
        "matched_branches": sorted({match.branch_label for match in candidate.matches if match.branch_label}),
        "matched_categories": sorted({match.category_label for match in candidate.matches if match.category_label}),
        "sources": sorted(candidate.source_names),
    }


def _ollama_chunk_text(chunk: dict[str, Any]) -> tuple[str, str]:
    message = chunk.get("message") if isinstance(chunk, dict) else None
    if not isinstance(message, dict):
        return "", ""
    return str(message.get("thinking") or ""), str(message.get("content") or "")


def _tool_call_screening_items(args: dict[str, Any]) -> list[Any]:
    for key in (
        "items",
        "results",
        "scores",
        "candidates",
        "screenings",
        "screening",
        "candidate_scores",
        "scored_candidates",
        "screening_results",
    ):
        value = args.get(key)
        if isinstance(value, list) and _looks_like_screening_items(value):
            return value
        if isinstance(value, dict):
            nested = _find_screening_items(value)
            if nested is not None:
                return nested
    nested = _find_screening_items(args)
    if nested is not None:
        return nested
    if isinstance(args.get("candidate_id") or args.get("id"), str):
        return [args]
    keys = ", ".join(sorted(str(key) for key in args.keys())) or "no keys"
    raise RuntimeError(f"Screening function call did not include a candidate score list. Argument keys: {keys}.")


def _find_screening_items(value: Any) -> list[Any] | None:
    if isinstance(value, list) and _looks_like_screening_items(value):
        return value
    if isinstance(value, dict):
        for nested in value.values():
            found = _find_screening_items(nested)
            if found is not None:
                return found
    return None


def _looks_like_screening_items(value: list[Any]) -> bool:
    if not value:
        return True
    return any(
        isinstance(item, dict)
        and isinstance(item.get("candidate_id") or item.get("id"), str)
        for item in value
    )


def _clamp_score(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return 0.0


def _parse_agent_json_list(raw_text: str) -> list[Any]:
    try:
        return parse_json_list(raw_text)
    except Exception:
        cleaned = _strip_code_fence(raw_text)
        starts = [index for index in (cleaned.find("["), cleaned.find("{")) if index >= 0]
        if starts:
            cleaned = cleaned[min(starts):]
        decoder = json.JSONDecoder()
        parsed, _end = decoder.raw_decode(cleaned)
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            raise ValueError(f"Screening agent returned {type(parsed)} instead of a JSON list.")
        return parsed


def _parse_screening_text_items(raw_text: str) -> list[Any] | None:
    try:
        items = _parse_agent_json_list(raw_text)
    except Exception:
        return None
    try:
        return _tool_call_screening_items({"items": items})
    except RuntimeError:
        return None


def _strip_code_fence(raw_text: str) -> str:
    cleaned = (raw_text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _truncate(value: str | None, max_chars: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
