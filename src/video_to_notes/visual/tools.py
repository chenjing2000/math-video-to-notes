from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..errors import StageError


def _resolve_explicit(value: str | None) -> Path | None:
    if not value or value == "auto":
        return None
    p = Path(value).expanduser()
    if p.exists() and p.is_file():
        return p.resolve()
    found = shutil.which(value)
    return Path(found).resolve() if found else None


def resolve_executable(
    name: str,
    configured: str | None = None,
) -> Path:
    explicit = _resolve_explicit(configured)
    if explicit:
        return explicit

    env_name = f"{name.upper()}_PATH"
    env_value = os.environ.get(env_name)
    if env_value:
        p = _resolve_explicit(env_value)
        if p:
            return p

    found = shutil.which(name)
    if found:
        return Path(found).resolve()

    raise StageError(
        f"找不到 {name}。请将其加入 PATH，或在 config/default.yaml 的 "
        f"tools.{name} 中指定可执行文件路径。"
    )


def resolve_ffmpeg_pair(config: dict) -> tuple[Path, Path]:
    tools = config.get("tools", {})
    ffmpeg = resolve_executable("ffmpeg", tools.get("ffmpeg"))

    try:
        ffprobe = resolve_executable("ffprobe", tools.get("ffprobe"))
    except StageError:
        sibling = ffmpeg.with_name(
            "ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe"
        )
        if sibling.exists():
            ffprobe = sibling
        else:
            raise

    return ffmpeg, ffprobe
