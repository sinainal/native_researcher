"""Known local llama.cpp launch profiles."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LlamaCppServerProfile:
    id: str
    label: str
    description: str
    context: int
    batch: int
    ubatch: int
    threads: int = 10
    threads_batch: int = 16
    n_gpu_layers: str = "all"
    n_cpu_moe: int | None = None
    cache_k: str = "f16"
    cache_v: str = "f16"
    cache_ram: int = 0
    fit_target: int | None = None
    direct_io: bool = True
    flash_attention: str = "on"
    reasoning: str = "off"
    no_cont_batching: bool = False
    no_webui: bool = True
    extra_args: tuple[str, ...] = field(default_factory=tuple)


LLAMACPP_SERVER_PROFILES: dict[str, LlamaCppServerProfile] = {
    "qwen36-q4km-safe": LlamaCppServerProfile(
        id="qwen36-q4km-safe",
        label="Qwen 3.6 35B Q4_K_M safe",
        description="Measured safe Q4_K_M profile: partial CPU MoE, direct I/O, turbo4/turbo3 KV.",
        context=32768,
        batch=1024,
        ubatch=256,
        n_cpu_moe=15,
        cache_k="turbo4",
        cache_v="turbo3",
        fit_target=1024,
    ),
    "qwen36-q4km-fast-risky": LlamaCppServerProfile(
        id="qwen36-q4km-fast-risky",
        label="Qwen 3.6 35B Q4_K_M fast risky",
        description="Slightly faster Q4_K_M profile with lower VRAM margin.",
        context=32768,
        batch=1024,
        ubatch=128,
        n_cpu_moe=14,
        cache_k="turbo4",
        cache_v="turbo3",
        fit_target=1024,
    ),
    "qwen36-q4km-64k-safe": LlamaCppServerProfile(
        id="qwen36-q4km-64k-safe",
        label="Qwen 3.6 35B Q4_K_M 64K safe",
        description="64K context variant of the measured safe Q4_K_M profile.",
        context=65536,
        batch=1024,
        ubatch=256,
        n_cpu_moe=15,
        cache_k="turbo4",
        cache_v="turbo3",
        fit_target=1024,
    ),
    "qwen36-iq4nl-safe": LlamaCppServerProfile(
        id="qwen36-iq4nl-safe",
        label="Qwen 3.6 35B IQ4_NL safe",
        description="Latest upstream CUDA 13 profile for the Unsloth IQ4_NL file.",
        context=65536,
        batch=512,
        ubatch=128,
        n_gpu_layers="all",
        cache_k="f16",
        cache_v="f16",
        fit_target=None,
        no_cont_batching=True,
    ),
    "gemma4-iq4nl-safe": LlamaCppServerProfile(
        id="gemma4-iq4nl-safe",
        label="Gemma 4 26B IQ4_NL safe",
        description="Existing Gemma 4 IQ4_NL full-GPU profile.",
        context=65536,
        batch=1024,
        ubatch=256,
        n_gpu_layers="all",
        cache_k="f16",
        cache_v="f16",
        fit_target=None,
        no_cont_batching=True,
    ),
    "gemma4-q4km-safe": LlamaCppServerProfile(
        id="gemma4-q4km-safe",
        label="Gemma 4 26B Q4_K_M safe",
        description="Gemma 4 Q4_K_M full-GPU profile using the same conservative runtime as IQ4_NL.",
        context=65536,
        batch=1024,
        ubatch=256,
        n_gpu_layers="all",
        cache_k="f16",
        cache_v="f16",
        fit_target=None,
        no_cont_batching=True,
    ),
}


def llama_cpp_profile_choices() -> list[dict[str, str]]:
    return [
        {
            "id": profile.id,
            "label": profile.label,
            "description": profile.description,
        }
        for profile in LLAMACPP_SERVER_PROFILES.values()
    ]


def build_llamacpp_server_args(profile_id: str, *, alias: str | None = None) -> str:
    profile = LLAMACPP_SERVER_PROFILES[profile_id]
    args = [
        "-c",
        str(profile.context),
        "-b",
        str(profile.batch),
        "-ub",
        str(profile.ubatch),
        "--threads",
        str(profile.threads),
        "--threads-batch",
        str(profile.threads_batch),
        "--parallel",
        "1",
        "-np",
        "1",
        "-ngl",
        profile.n_gpu_layers,
        "--flash-attn",
        profile.flash_attention,
        "--cache-ram",
        str(profile.cache_ram),
        "--reasoning",
        profile.reasoning,
        "--no-warmup",
    ]
    if profile.no_cont_batching:
        args.append("--no-cont-batching")
    if profile.no_webui:
        args.append("--no-webui")
    if profile.direct_io:
        args.append("--direct-io")
    if profile.n_cpu_moe is not None:
        args.extend(["--n-cpu-moe", str(profile.n_cpu_moe)])
    if profile.cache_k != "f16":
        args.extend(["-ctk", profile.cache_k])
    if profile.cache_v != "f16":
        args.extend(["-ctv", profile.cache_v])
    if profile.fit_target is not None:
        args.extend(["-fitt", str(profile.fit_target)])
    if alias:
        args.extend(["--alias", alias])
    args.extend(profile.extra_args)
    return shlex.join(args)


def detect_llamacpp_profile(server_args: str) -> str:
    normalized = " ".join(shlex.split(server_args or ""))
    for profile_id in LLAMACPP_SERVER_PROFILES:
        candidate = " ".join(
            token
            for token in shlex.split(build_llamacpp_server_args(profile_id))
            if token != "--alias"
        )
        if candidate and candidate in normalized:
            return profile_id
    return "custom"
