"""llama.cpp model discovery helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from app.llm.llamacpp_profiles import detect_llamacpp_profile
from app.schemas.settings import LlamaCppModelInfo, LlamaCppSettingsPayload

MIN_LLAMA_MODEL_BYTES = 1 * 1024 * 1024 * 1024


def model_alias_from_path(path: Path) -> str:
    alias = path.stem.strip()
    alias = re.sub(r"(?i)\.gguf$", "", alias)
    alias = re.sub(r"[^A-Za-z0-9._:+-]+", "-", alias).strip("-")
    return alias or "local"


def profile_for_llamacpp_model(path: Path) -> str | None:
    name = path.name.lower()
    if "qwen3.6" in name or "qwen36" in name:
        if "iq4_nl" in name or "iq4-nl" in name:
            return "qwen36-iq4nl-safe"
        if "q4_k_m" in name or "q4-k-m" in name or "q4km" in name:
            return "qwen36-q4km-safe"
    if "gemma-4" in name or "gemma4" in name:
        if "iq4_nl" in name or "iq4-nl" in name:
            return "gemma4-iq4nl-safe"
        if "q4_k_m" in name or "q4-k-m" in name or "q4km" in name:
            return "gemma4-q4km-safe"
    return None


def _path_list_from_env(*names: str) -> list[Path]:
    roots: list[Path] = []
    for name in names:
        raw = os.getenv(name, "")
        for item in raw.split(os.pathsep):
            value = item.strip()
            if value:
                roots.append(Path(value).expanduser())
    return roots


def llamacpp_discovery_roots(settings: Any | None = None) -> list[Path]:
    roots = _path_list_from_env("LLAMACPP_MODEL_ROOTS", "LOCAL_LLM_MODEL_ROOTS")
    configured_model = str(getattr(settings, "llamacpp_model_path", "") or "").strip() if settings is not None else ""
    if configured_model:
        roots.append(Path(configured_model).expanduser().parent)

    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved in seen or not root.exists():
            continue
        seen.add(resolved)
        unique.append(root)
    return unique


def discover_llamacpp_model_files(settings: Any | None = None) -> list[LlamaCppModelInfo]:
    by_path: dict[str, LlamaCppModelInfo] = {}
    used_ids: set[str] = set()
    for root in llamacpp_discovery_roots(settings):
        try:
            files = root.rglob("*.gguf") if root.is_dir() else [root]
            for path in files:
                if not path.is_file():
                    continue
                name = path.name.lower()
                if name.startswith("ggml-vocab") or "vocab" in name:
                    continue
                try:
                    size = path.stat().st_size
                    resolved = str(path.resolve())
                except OSError:
                    continue
                if size < MIN_LLAMA_MODEL_BYTES:
                    continue
                if resolved in by_path:
                    continue
                alias = model_alias_from_path(path)
                if alias in used_ids:
                    parent_alias = model_alias_from_path(path.parent / f"{path.parent.name}-{path.name}")
                    alias = parent_alias if parent_alias not in used_ids else f"{alias}-{len(used_ids) + 1}"
                used_ids.add(alias)
                by_path[resolved] = LlamaCppModelInfo(
                    id=alias,
                    object="model",
                    path=resolved,
                    size=size,
                    profile=profile_for_llamacpp_model(path),
                    running=False,
                )
        except OSError:
            continue
    return sorted(by_path.values(), key=lambda item: item.id.lower())


def merge_llamacpp_models(
    discovered: list[LlamaCppModelInfo],
    served: list[LlamaCppModelInfo],
    configured: LlamaCppSettingsPayload,
) -> list[LlamaCppModelInfo]:
    by_id: dict[str, LlamaCppModelInfo] = {}
    for item in discovered:
        by_id[item.id] = item
    for item in served:
        existing = by_id.get(item.id)
        by_id[item.id] = LlamaCppModelInfo(
            id=item.id,
            object=item.object or (existing.object if existing else None),
            path=existing.path if existing else item.path,
            size=existing.size if existing else item.size,
            profile=existing.profile if existing else item.profile,
            running=True,
        )
    if configured.llamacpp_model and configured.llamacpp_model not in by_id:
        by_id[configured.llamacpp_model] = LlamaCppModelInfo(
            id=configured.llamacpp_model,
            object="model",
            path=configured.llamacpp_model_path or None,
            profile=detect_llamacpp_profile(configured.llamacpp_server_args) or None,
            running=False,
        )
    return sorted(by_id.values(), key=lambda item: item.id.lower())


def resolve_llamacpp_model_path(model: str, settings: Any | None = None) -> str:
    normalized = str(model or "").strip()
    if not normalized:
        return ""
    for item in discover_llamacpp_model_files(settings):
        if item.id == normalized and item.path:
            return item.path
    return ""
