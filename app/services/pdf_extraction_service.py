"""Question answering over downloaded PDF or full-text XML artifacts."""

from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from app.genai import create_genai_client, load_genai_sdk
from app.llm import llamacpp_chat, ollama_chat, resolve_chat_model_target
from app.schemas.article import ArticleReference
from app.schemas.pdf import PDFDownloadRequest
from app.schemas.pdf_extraction import (
    PDFExtractionAnswer,
    PDFExtractionEvidence,
    PDFExtractionRequest,
    PDFExtractionResponse,
    PDFExtractionResult,
)

MAX_FULL_TEXT_CHARS = 180_000


class PDFExtractionService:
    def __init__(self, *, pdf_service: Any, settings: Any | None = None) -> None:
        self.pdf_service = pdf_service
        self.settings = settings

    async def extract(self, request: PDFExtractionRequest) -> PDFExtractionResponse:
        articles = request.articles[: request.max_articles or len(request.articles)]
        questions = [item.strip() for item in request.questions if item.strip()]
        if not questions:
            questions = ["What evidence in this full text is relevant to the research objective?"]

        download = await self.pdf_service.download_articles(
            PDFDownloadRequest(
                articles=articles,
                download_dir=request.download_dir,
                max_articles=len(articles) or None,
                downloader_mode=request.downloader_mode,
            )
        )
        results: list[PDFExtractionResult] = []
        for item in download.results:
            if not item.success or not item.file_path:
                results.append(
                    PDFExtractionResult(
                        article=item.article,
                        success=False,
                        file_path=item.file_path,
                        content_kind=item.content_kind,
                        error=item.error or "Download failed.",
                    )
                )
                continue
            try:
                text = extract_text_from_artifact(Path(item.file_path))
                answers = await self._answer_questions(
                    item.article,
                    text,
                    questions,
                    extraction_fields=request.extraction_fields,
                    model=request.model,
                    api_key=request.api_key,
                    thinking_level=request.thinking_level,
                )
                results.append(
                    PDFExtractionResult(
                        article=item.article,
                        success=True,
                        file_path=item.file_path,
                        content_kind=item.content_kind,
                        text_chars=len(text),
                        answers=answers,
                    )
                )
            except Exception as exc:
                results.append(
                    PDFExtractionResult(
                        article=item.article,
                        success=False,
                        file_path=item.file_path,
                        content_kind=item.content_kind,
                        error=str(exc),
                    )
                )

        success_count = sum(1 for item in results if item.success)
        return PDFExtractionResponse(
            total=len(results),
            success_count=success_count,
            failed_count=len(results) - success_count,
            questions=questions,
            results=results,
            meta={"model": request.model or "", "download_success_count": download.success_count},
        )

    async def _answer_questions(
        self,
        article: ArticleReference,
        text: str,
        questions: list[str],
        *,
        extraction_fields: list[str],
        model: str | None,
        api_key: str,
        thinking_level: str,
    ) -> list[PDFExtractionAnswer]:
        if not text.strip():
            raise RuntimeError("Downloaded artifact did not contain extractable text.")
        if not model:
            return deterministic_pdf_answers(text, questions)
        model_target = resolve_chat_model_target(model, settings=self.settings)
        prompt = json.dumps(
            {
                "task": (
                    "Answer the questions using only the provided full text. Return JSON list only. "
                    "Keep each answer under 80 words and include at most 3 evidence items per question."
                ),
                "required_shape": {
                    "question": "string",
                    "answer": "string",
                    "confidence": 0.0,
                    "evidence": [{"quote": "short exact quote", "page": None, "section": "string", "confidence": 0.0}],
                },
                "article": {
                    "title": article.title,
                    "year": article.year,
                    "doi": article.doi,
                    "pmid": article.pmid,
                    "pmc_id": article.pmc_id,
                },
                "questions": questions,
                "extraction_fields": extraction_fields,
                "full_text": text[:MAX_FULL_TEXT_CHARS],
            },
            ensure_ascii=False,
        )
        if model_target.provider in {"ollama", "llamacpp"}:
            local_chat = llamacpp_chat if model_target.provider == "llamacpp" else ollama_chat
            base_url_attr = "llamacpp_base_url" if model_target.provider == "llamacpp" else "ollama_base_url"
            default_base_url = "http://localhost:8098" if model_target.provider == "llamacpp" else "http://localhost:11434"
            response = await local_chat(
                base_url=str(getattr(self.settings, base_url_attr, default_base_url) or default_base_url),
                model=model_target.model_name,
                messages=[
                    {"role": "system", "content": "You extract evidence from full-text papers. Return JSON only."},
                    {"role": "user", "content": prompt},
                ],
                tools=None,
                thinking_level=thinking_level,
                request_user_agent=str(getattr(self.settings, "request_user_agent", "NativeResearcher/0.1") or "NativeResearcher/0.1"),
            )
            raw_text = str((response.get("message") or {}).get("content") or "")
        else:
            if len((api_key or "").strip()) < 10:
                raise RuntimeError("PDF extraction requires an API key for Gemini models.")
            _genai, types = load_genai_sdk()
            client = create_genai_client(api_key)

            def _generate() -> str:
                response = client.models.generate_content(
                    model=model_target.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction="You extract evidence from full-text papers. Return JSON only.",
                        response_mime_type="application/json",
                    ),
                )
                return str(getattr(response, "text", None) or "")

            raw_text = await asyncio.to_thread(_generate)
        return normalize_pdf_answer_items(parse_json_items(raw_text), questions)


def extract_text_from_artifact(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return extract_xml_text(path.read_text(encoding="utf-8", errors="ignore"))
    if suffix == ".pdf":
        return extract_pdf_text(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_xml_text(raw_xml: str) -> str:
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return re.sub(r"\s+", " ", raw_xml).strip()
    chunks = []
    for node in root.iter():
        if node.text and node.text.strip():
            chunks.append(node.text.strip())
    return re.sub(r"\s+", " ", " ".join(chunks)).strip()


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise RuntimeError("pypdf is required to extract text from PDF files.") from exc
    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"[page {index}]\n{text.strip()}")
    return "\n\n".join(pages).strip()


def deterministic_pdf_answers(text: str, questions: list[str]) -> list[PDFExtractionAnswer]:
    lower_text = text.lower()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    answers = []
    for question in questions:
        terms = [term for term in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", question.lower()) if term not in {"what", "which", "does", "this", "that", "from", "with", "paper", "evidence"}]
        ranked = sorted(
            sentences,
            key=lambda sentence: sum(1 for term in terms if term in sentence.lower()),
            reverse=True,
        )
        quote = next((sentence.strip() for sentence in ranked if sentence.strip()), text[:500].strip())
        score = min(1.0, sum(1 for term in terms if term in lower_text) / max(1, len(terms)))
        answers.append(
            PDFExtractionAnswer(
                question=question,
                answer=quote[:900] if quote else "No direct answer found in extracted text.",
                evidence=[PDFExtractionEvidence(quote=quote[:500], section="full text", confidence=round(score, 3))] if quote else [],
                confidence=round(score, 3),
            )
        )
    return answers


def parse_json_items(raw_text: str) -> list[Any]:
    cleaned = (raw_text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    starts = [index for index in (cleaned.find("["), cleaned.find("{")) if index >= 0]
    if starts:
        cleaned = cleaned[min(starts):]
    parsed = json.JSONDecoder().raw_decode(cleaned)[0]
    if isinstance(parsed, dict):
        parsed = parsed.get("items") or parsed.get("answers") or [parsed]
    if not isinstance(parsed, list):
        raise RuntimeError("PDF extraction model did not return a JSON list.")
    return parsed


def normalize_pdf_answer_items(items: list[Any], questions: list[str]) -> list[PDFExtractionAnswer]:
    normalized: list[PDFExtractionAnswer] = []
    for index, question in enumerate(questions):
        item = next((entry for entry in items if isinstance(entry, dict) and str(entry.get("question") or "") == question), None)
        if item is None and index < len(items) and isinstance(items[index], dict):
            item = items[index]
        item = item or {}
        evidence = []
        for raw_evidence in item.get("evidence") or []:
            if not isinstance(raw_evidence, dict):
                raw_evidence = {"quote": str(raw_evidence)}
            evidence.append(
                PDFExtractionEvidence(
                    quote=str(raw_evidence.get("quote") or "")[:1000],
                    page=_optional_int(raw_evidence.get("page")),
                    section=str(raw_evidence.get("section") or "")[:200],
                    confidence=_clamp(raw_evidence.get("confidence")),
                )
            )
        normalized.append(
            PDFExtractionAnswer(
                question=question,
                answer=str(item.get("answer") or "")[:2000],
                evidence=evidence[:8],
                confidence=_clamp(item.get("confidence")),
            )
        )
    return normalized


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return 0.0
