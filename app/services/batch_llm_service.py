"""Batch LLM processing for article abstracts."""

from __future__ import annotations

import asyncio
import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.genai import create_genai_client, load_genai_sdk, resolve_helper_model_name
from app.schemas.llm import LLMBatchReport, LLMProcessRequest, LLMProcessResponse

LEGACY_BATCH_SYSTEM_INSTRUCTION = (
    "You are the legacy batch abstract analysis engine for Researcher_2. "
    "You receive article inputs as a JSON list. "
    "Your response must always be only a valid JSON list. "
    "Every item must include `id`, and you may only use IDs from the provided inputs. "
    "Do not invent articles outside the input, add prose outside the JSON, or use markdown."
)

ANALYZER_BATCH_SYSTEM_INSTRUCTION = (
    "You are the batch analyzer subagent inside Researcher_2. "
    "You screen batches of biomedical articles for a research agent. "
    "You must use only the provided article data. "
    "Never invent findings, study design details, populations, interventions, or outcomes. "
    "Return valid JSON only. "
    "Each output item must preserve the input `id` and must correspond to exactly one input article."
)

DEFAULT_SCREEN_FOR_QUESTION_SCHEMA: dict[str, Any] = {
    "id": 0,
    "in_scope": False,
    "relevance_score": 0,
    "confidence": "low",
    "answers_question": False,
    "population_match": False,
    "intervention_match": False,
    "outcome_match": False,
    "evidence_summary": "",
    "short_reason": "",
    "matched_terms": [],
}

CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(slots=True)
class PreparedArticle:
    id: int
    source: dict[str, Any]
    payload: dict[str, Any]
    estimated_tokens: int


@dataclass(slots=True)
class PlannedBatch:
    number: int
    articles: list[PreparedArticle] = field(default_factory=list)
    estimated_tokens: int = 0

    @property
    def article_ids(self) -> list[int]:
        return [item.id for item in self.articles]


class BatchLLMService:
    async def process(self, payload: LLMProcessRequest) -> LLMProcessResponse:
        if not payload.articles:
            raise ValueError("No articles were provided for LLM processing.")

        model_name = resolve_helper_model_name(payload.model)
        source_articles = [article.model_dump() for article in payload.articles]
        articles = self._resolve_scope(source_articles, payload.selected_ids)
        if not articles:
            raise ValueError("No articles match the selected processing scope.")

        analysis_mode = payload.analysis_mode
        prompt = self._resolve_prompt(payload)
        system_instruction = self._resolve_system_instruction(payload)
        schema_template = self._resolve_schema_template(payload)

        logs: list[str] = []
        errors: list[str] = []
        prepared = [self._prepare_article(article) for article in articles]
        prompt_tokens = estimate_token_count(prompt)
        average_article_tokens = max(
            1,
            sum(item.estimated_tokens for item in prepared) // max(1, len(prepared)),
        )
        batch_token_budget = max(
            16_000,
            min(50_000, prompt_tokens + average_article_tokens * payload.llm_batch + 3_000),
        )
        batches = self._plan_batches(
            prepared,
            max_batch_size=payload.llm_batch,
            batch_token_budget=batch_token_budget,
            dynamic_batch=payload.dynamic_batch,
        )

        logs.append(
            "Batch analyzer plan prepared: "
            f"mode={analysis_mode}, {len(articles)} articles, {len(batches)} batches, "
            f"target batch size {payload.llm_batch}, token budget {batch_token_budget}."
        )
        logs.append("Abstract trimming is disabled: full abstract text is used.")

        merged_by_id = {int(article["id"]): dict(article) for article in articles}
        batch_reports: list[LLMBatchReport] = []
        total_processed = 0

        for batch in batches:
            logs.append(
                f"Batch {batch.number} starting: {len(batch.articles)} articles, "
                f"estimated {batch.estimated_tokens} tokens."
            )
            try:
                results, attempts = await self._run_batch_with_retries(
                    api_key=payload.api_key,
                    model_name=model_name,
                    prompt=prompt,
                    system_instruction=system_instruction,
                    batch=batch,
                    retry_count=payload.retry_count,
                    schema_template=schema_template,
                )
                merged_count = self._merge_results(merged_by_id, results)
                total_processed += len(results)
                batch_reports.append(
                    LLMBatchReport(
                        batch_number=batch.number,
                        article_ids=batch.article_ids,
                        article_count=len(batch.articles),
                        estimated_input_tokens=batch.estimated_tokens,
                        attempts=attempts,
                        output_count=len(results),
                        status="success",
                    )
                )
                logs.append(
                    f"Batch {batch.number} completed: {len(results)} outputs, "
                    f"{merged_count} articles merged."
                )
            except Exception as exc:
                error_message = f"Batch {batch.number} failed: {exc}"
                errors.append(error_message)
                batch_reports.append(
                    LLMBatchReport(
                        batch_number=batch.number,
                        article_ids=batch.article_ids,
                        article_count=len(batch.articles),
                        estimated_input_tokens=batch.estimated_tokens,
                        attempts=payload.retry_count + 1,
                        output_count=0,
                        status="error",
                        error=str(exc),
                    )
                )
                logs.append(error_message)

        processed_articles = sorted(merged_by_id.values(), key=lambda item: int(item.get("id", 0)))
        merged_count = sum(1 for article in processed_articles if article.get("_llm_processed"))
        for article in processed_articles:
            article.pop("_llm_processed", None)

        top_article_ids, aggregate_summary = self._build_aggregate_summary(
            processed_articles,
            top_k=payload.top_k,
        )

        return LLMProcessResponse(
            model=model_name,
            analysis_mode=analysis_mode,
            article_scope="selected" if payload.selected_ids else "all",
            article_count=len(articles),
            batch_count=len(batches),
            processed_count=total_processed,
            merged_count=merged_count,
            top_article_ids=top_article_ids,
            aggregate_summary=aggregate_summary,
            logs=logs,
            errors=errors,
            batches=batch_reports,
            processed_articles=processed_articles,
        )

    @staticmethod
    def _resolve_scope(
        articles: list[dict[str, Any]],
        selected_ids: list[int],
    ) -> list[dict[str, Any]]:
        if not selected_ids:
            return articles
        selected_set = set(selected_ids)
        resolved = [article for article in articles if int(article["id"]) in selected_set]
        return resolved or articles

    @staticmethod
    def _resolve_system_instruction(payload: LLMProcessRequest) -> str:
        if payload.analysis_mode == "screen_for_question":
            return ANALYZER_BATCH_SYSTEM_INSTRUCTION
        return ANALYZER_BATCH_SYSTEM_INSTRUCTION if payload.output_schema else LEGACY_BATCH_SYSTEM_INSTRUCTION

    @staticmethod
    def _resolve_schema_template(payload: LLMProcessRequest) -> dict[str, Any] | None:
        template = payload.output_schema
        if payload.analysis_mode == "screen_for_question":
            template = template or DEFAULT_SCREEN_FOR_QUESTION_SCHEMA
        if template is None:
            return None
        normalized = copy.deepcopy(template)
        normalized["id"] = normalized.get("id", 0)
        return normalized

    def _resolve_prompt(self, payload: LLMProcessRequest) -> str:
        schema_template = self._resolve_schema_template(payload)
        if payload.analysis_mode == "screen_for_question":
            return self._build_screen_for_question_prompt(
                question=(payload.question or payload.prompt).strip(),
                schema_template=schema_template or DEFAULT_SCREEN_FOR_QUESTION_SCHEMA,
                extra_instructions=payload.prompt.strip() if payload.question and payload.prompt.strip() else "",
            )
        return self._build_custom_prompt(
            prompt=payload.prompt.strip(),
            schema_template=schema_template,
        )

    @staticmethod
    def _build_custom_prompt(
        *,
        prompt: str,
        schema_template: dict[str, Any] | None,
    ) -> str:
        if not schema_template:
            return prompt
        schema_json = json.dumps(schema_template, ensure_ascii=False, indent=2)
        return (
            f"{prompt}\n\n"
            "Return one JSON array with one object per input article.\n"
            "Use this exact per-article schema:\n"
            f"{schema_json}\n\n"
            "Rules:\n"
            "- Preserve the input `id` exactly.\n"
            "- Use only the supplied article data.\n"
            "- Return JSON only.\n"
        )

    def _build_screen_for_question_prompt(
        self,
        *,
        question: str,
        schema_template: dict[str, Any],
        extra_instructions: str,
    ) -> str:
        schema_json = json.dumps(schema_template, ensure_ascii=False, indent=2)
        rules: list[str] = [
            "Task: decide how useful each article is for answering the research question.",
            f"Research question: {question}",
            "Return one JSON array with one object for every input article.",
            "Use only the provided title, abstract, and metadata.",
            "Do not invent results, methods, mechanisms, populations, or conclusions.",
            "Be conservative: when the abstract is insufficient, lower confidence and say so briefly.",
            "Keep `short_reason` concise.",
            "Keep `evidence_summary` concise and evidence-grounded.",
        ]
        if "relevance_score" in schema_template:
            rules.append("`relevance_score` must be an integer from 0 to 100.")
        if "confidence" in schema_template:
            rules.append("`confidence` must be one of: low, medium, high.")
        if "matched_terms" in schema_template:
            rules.append("`matched_terms` should contain only short terms or concepts actually supported by the article.")
        if extra_instructions:
            rules.append(f"Extra instructions: {extra_instructions}")

        rule_block = "\n".join(f"- {rule}" for rule in rules)
        return (
            "You are the batch analyzer subagent inside Researcher_2.\n"
            "Screen a batch of biomedical articles against a research question and return strict JSON.\n\n"
            "Per-article output schema:\n"
            f"{schema_json}\n\n"
            "Rules:\n"
            f"{rule_block}\n"
        )

    def _prepare_article(self, article: dict[str, Any]) -> PreparedArticle:
        payload = {
            "id": int(article["id"]),
            "title": sanitize_text(article.get("title") or ""),
            "abstract": sanitize_text(article.get("abstract") or ""),
            "year": article.get("year"),
            "journal": article.get("journal"),
            "article_type": article.get("article_type"),
            "article_types": list(article.get("article_types") or [])[:10],
            "citation_count": article.get("citation_count"),
            "mesh_terms": list(article.get("mesh_terms") or [])[:15],
            "keywords": list(article.get("keywords") or [])[:15],
            "authors": list(article.get("authors") or [])[:12],
            "related_articles": list(article.get("related_articles") or [])[:10],
            "pmid": article.get("pmid"),
            "doi": article.get("doi"),
        }
        estimated_tokens = estimate_token_count(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        return PreparedArticle(
            id=payload["id"],
            source=dict(article),
            payload=payload,
            estimated_tokens=estimated_tokens,
        )

    def _plan_batches(
        self,
        articles: list[PreparedArticle],
        *,
        max_batch_size: int,
        batch_token_budget: int,
        dynamic_batch: bool,
    ) -> list[PlannedBatch]:
        if not articles:
            return []

        planned: list[PlannedBatch] = []
        if dynamic_batch:
            ordered = sorted(articles, key=lambda item: item.estimated_tokens, reverse=True)
            for article in ordered:
                target = None
                for batch in planned:
                    if len(batch.articles) >= max_batch_size:
                        continue
                    if batch.estimated_tokens + article.estimated_tokens <= batch_token_budget:
                        target = batch
                        break
                if target is None:
                    target = PlannedBatch(number=len(planned) + 1)
                    planned.append(target)
                target.articles.append(article)
                target.estimated_tokens += article.estimated_tokens
            return planned

        current = PlannedBatch(number=1)
        for article in articles:
            needs_split = (
                current.articles
                and (
                    len(current.articles) >= max_batch_size
                    or current.estimated_tokens + article.estimated_tokens > batch_token_budget
                )
            )
            if needs_split:
                planned.append(current)
                current = PlannedBatch(number=len(planned) + 1)
            current.articles.append(article)
            current.estimated_tokens += article.estimated_tokens
        if current.articles:
            planned.append(current)
        return planned

    async def _run_batch_with_retries(
        self,
        *,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str,
        batch: PlannedBatch,
        retry_count: int,
        schema_template: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], int]:
        last_error: Exception | None = None
        for attempt in range(1, retry_count + 2):
            try:
                results = await asyncio.to_thread(
                    self._run_batch_once,
                    api_key,
                    model_name,
                    prompt,
                    system_instruction,
                    batch,
                    schema_template,
                )
                return results, attempt
            except Exception as exc:
                last_error = exc
                if attempt > retry_count:
                    break
                await asyncio.sleep(extract_retry_delay(str(exc), attempt))
        assert last_error is not None
        raise last_error

    def _run_batch_once(
        self,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str,
        batch: PlannedBatch,
        schema_template: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        _genai, types = load_genai_sdk()
        client = create_genai_client(api_key)
        batch_payload = [article.payload for article in batch.articles]
        full_prompt = (
            f"{prompt.strip()}\n\n"
            "Article inputs:\n"
            f"{json.dumps(batch_payload, ensure_ascii=False)}"
        )
        response = client.models.generate_content(
            model=model_name,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
            ),
        )
        raw_text = (getattr(response, "text", None) or "").strip()
        parsed = parse_json_list(raw_text)
        allowed_ids = {article.id for article in batch.articles}
        validated: list[dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            if "id" not in item:
                continue
            try:
                article_id = int(item["id"])
            except (TypeError, ValueError):
                continue
            if article_id not in allowed_ids:
                continue
            validated.append(self._normalize_result_item(article_id, item, schema_template))
        if not validated:
            raise ValueError("Model gecerli JSON sonuc donmedi.")
        return validated

    @staticmethod
    def _normalize_result_item(
        article_id: int,
        item: dict[str, Any],
        schema_template: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not schema_template:
            normalized = dict(item)
            normalized["id"] = article_id
            return normalized

        normalized: dict[str, Any] = {"id": article_id}
        for key, default_value in schema_template.items():
            if key == "id":
                continue
            normalized[key] = copy.deepcopy(item.get(key, default_value))
        return normalized

    @staticmethod
    def _merge_results(
        merged_by_id: dict[int, dict[str, Any]],
        results: list[dict[str, Any]],
    ) -> int:
        merged_count = 0
        for result in results:
            article_id = int(result["id"])
            existing = merged_by_id.get(article_id)
            if existing is None:
                continue
            for key, value in result.items():
                if key == "id":
                    continue
                existing[key] = value
            existing["_llm_processed"] = True
            merged_count += 1
        return merged_count

    def _build_aggregate_summary(
        self,
        processed_articles: list[dict[str, Any]],
        *,
        top_k: int,
    ) -> tuple[list[int], dict[str, Any]]:
        analyzed_articles = [
            article
            for article in processed_articles
            if any(
                field_name in article
                for field_name in (
                    "in_scope",
                    "relevance_score",
                    "confidence",
                    "answers_question",
                    "population_match",
                    "intervention_match",
                    "outcome_match",
                    "evidence_summary",
                    "short_reason",
                )
            )
        ]
        scored_articles = sorted(
            analyzed_articles,
            key=self._article_priority_score,
            reverse=True,
        )
        top_article_ids = [int(article["id"]) for article in scored_articles[:top_k]]

        relevance_scores = [
            int(article["relevance_score"])
            for article in analyzed_articles
            if article.get("relevance_score") is not None and str(article.get("relevance_score")).isdigit()
        ]
        aggregate_summary: dict[str, Any] = {
            "top_k": top_k,
            "top_candidates_count": len(top_article_ids),
            "processed_article_count": len(analyzed_articles),
            "article_pool_count": len(processed_articles),
        }
        if any("in_scope" in article for article in analyzed_articles):
            aggregate_summary["in_scope_count"] = sum(
                1 for article in analyzed_articles if bool(article.get("in_scope"))
            )
        if any("answers_question" in article for article in analyzed_articles):
            aggregate_summary["answers_question_count"] = sum(
                1 for article in analyzed_articles if bool(article.get("answers_question"))
            )
        if any("confidence" in article for article in analyzed_articles):
            aggregate_summary["high_confidence_count"] = sum(
                1
                for article in analyzed_articles
                if str(article.get("confidence", "")).strip().lower() == "high"
            )
        if relevance_scores:
            aggregate_summary["average_relevance_score"] = round(
                sum(relevance_scores) / len(relevance_scores),
                2,
            )
        return top_article_ids, aggregate_summary

    @staticmethod
    def _article_priority_score(article: dict[str, Any]) -> float:
        score = 0.0
        if bool(article.get("in_scope")):
            score += 1_000
        if bool(article.get("answers_question")):
            score += 900
        for field_name in ("population_match", "intervention_match", "outcome_match"):
            if bool(article.get(field_name)):
                score += 120

        relevance_raw = article.get("relevance_score")
        try:
            relevance_score = int(relevance_raw)
        except (TypeError, ValueError):
            relevance_score = 0
        score += max(0, min(100, relevance_score)) * 10

        confidence = str(article.get("confidence", "")).strip().lower()
        score += CONFIDENCE_RANK.get(confidence, 0) * 25

        if article.get("evidence_summary"):
            score += 5
        if article.get("short_reason"):
            score += 3
        return score


def sanitize_text(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value or "").replace("\x00", " ").strip()


def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4 + 1)


def extract_retry_delay(error_message: str, attempt: int) -> float:
    match = re.search(r"retry_delay\s*{\s*seconds:\s*(\d+)", error_message or "")
    if match:
        return float(match.group(1))
    return min(2**attempt, 12)


def parse_json_list(raw_text: str) -> list[Any]:
    cleaned = (raw_text or "").strip()
    if not cleaned:
        raise ValueError("Model bos yanit dondu.")
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        candidate = extract_json_block(cleaned)
        if candidate is None:
            raise
        parsed = json.loads(candidate)

    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError(f"Beklenen JSON liste yerine {type(parsed)} alindi.")
    return parsed


def extract_json_block(raw_text: str) -> str | None:
    array_match = re.search(r"(\[\s*.*\s*\])", raw_text, flags=re.DOTALL)
    if array_match:
        return array_match.group(1)
    object_match = re.search(r"(\{\s*.*\s*\})", raw_text, flags=re.DOTALL)
    if object_match:
        return object_match.group(1)
    return None
