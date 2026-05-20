"""Small file-backed runtime settings helpers."""

from __future__ import annotations

from pathlib import Path


def read_value(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_value(path: Path, value: str) -> None:
    cleaned = value.strip()
    if not cleaned:
        try:
            path.unlink()
        except OSError:
            return
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cleaned + "\n", encoding="utf-8")


def write_bool_value(path: Path, value: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(("true" if value else "false") + "\n", encoding="utf-8")


def read_bool_value(path: Path, default: bool) -> bool:
    raw = read_value(path).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default
