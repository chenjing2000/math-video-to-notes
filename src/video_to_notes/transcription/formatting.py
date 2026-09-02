from __future__ import annotations

from pathlib import Path
from typing import Any

from ..util import atomic_write_json


def _srt_timestamp(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_transcript_json(
    path: Path,
    *,
    metadata: dict[str, Any],
    segments: list[dict[str, Any]],
) -> None:
    atomic_write_json(path, {
        "schema_version": "1.0",
        "metadata": metadata,
        "segments": segments,
    })


def write_transcript_srt(
    path: Path,
    segments: list[dict[str, Any]],
) -> None:
    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(
            f"{_srt_timestamp(float(seg['start']))} --> "
            f"{_srt_timestamp(float(seg['end']))}"
        )
        lines.append(str(seg["text"]).strip())
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_transcript_txt(
    path: Path,
    segments: list[dict[str, Any]],
) -> None:
    lines = [str(seg["text"]).strip() for seg in segments]
    path.write_text("\n".join(line for line in lines if line), encoding="utf-8")
