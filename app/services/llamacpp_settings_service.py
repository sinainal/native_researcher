"""llama.cpp settings payload, runtime, probe, and warmup helpers."""

from __future__ import annotations

from typing import Any

from app.llm.llamacpp import llamacpp_chat
from app.llm.llamacpp_profiles import detect_llamacpp_profile
from app.schemas.settings import LlamaCppModelInfo, LlamaCppSettingsPayload
from app.services.local_llamacpp_supervisor import probe_llamacpp_server
from app.services.runtime_settings_store import read_bool_value, read_value


def normalize_llamacpp_base_url(value: str | None, default: str = "http://localhost:8098") -> str:
    normalized = (value or "").strip() or default.strip()
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized.rstrip("/")


def current_llamacpp_payload(settings: Any) -> LlamaCppSettingsPayload:
    server_args = (
        read_value(settings.llamacpp_server_args_path)
        or str(getattr(settings, "llamacpp_server_args", "") or "")
    )
    return LlamaCppSettingsPayload(
        llamacpp_base_url=normalize_llamacpp_base_url(
            read_value(settings.llamacpp_base_url_path),
            str(getattr(settings, "llamacpp_base_url", "http://localhost:8098")),
        ),
        llamacpp_model=read_value(settings.llamacpp_model_name_path)
        or str(getattr(settings, "llamacpp_model", "") or "")
        or "local",
        llamacpp_executable=read_value(settings.llamacpp_executable_path)
        or str(getattr(settings, "llamacpp_executable", "") or ""),
        llamacpp_model_path=read_value(settings.llamacpp_model_path_path)
        or str(getattr(settings, "llamacpp_model_path", "") or ""),
        llamacpp_library_path=read_value(settings.llamacpp_library_path_path)
        or str(getattr(settings, "llamacpp_library_path", "") or ""),
        llamacpp_server_args=server_args,
        llamacpp_profile=detect_llamacpp_profile(server_args),
        llamacpp_auto_start=read_bool_value(
            settings.llamacpp_auto_start_path,
            bool(getattr(settings, "llamacpp_auto_start", True)),
        ),
    )


def apply_llamacpp_runtime_settings(settings: Any, payload: LlamaCppSettingsPayload) -> None:
    object.__setattr__(settings, "llamacpp_base_url", payload.llamacpp_base_url)
    object.__setattr__(settings, "llamacpp_model", payload.llamacpp_model)
    object.__setattr__(settings, "llamacpp_executable", payload.llamacpp_executable)
    object.__setattr__(settings, "llamacpp_model_path", payload.llamacpp_model_path)
    object.__setattr__(settings, "llamacpp_library_path", payload.llamacpp_library_path)
    object.__setattr__(settings, "llamacpp_server_args", payload.llamacpp_server_args)
    object.__setattr__(settings, "llamacpp_auto_start", payload.llamacpp_auto_start)


async def probe_llamacpp(
    base_url: str,
    *,
    request_user_agent: str,
) -> tuple[bool, list[LlamaCppModelInfo], str | None]:
    result = await probe_llamacpp_server(base_url, request_user_agent=request_user_agent)
    return (
        result.connected,
        [LlamaCppModelInfo(id=model) for model in result.models],
        result.error,
    )


async def warmup_llamacpp(
    *,
    base_url: str,
    model: str,
    request_user_agent: str,
) -> str | None:
    try:
        await llamacpp_chat(
            base_url=base_url,
            model=model or "local",
            messages=[{"role": "user", "content": "Warm up the model and reply with a single word."}],
            timeout_seconds=600.0,
            request_user_agent=request_user_agent,
        )
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
