from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ..errors import StageError
from ..util import atomic_write_json


def _parse_rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    if "/" in value:
        a, b = value.split("/", 1)
        try:
            den = float(b)
            return float(a) / den if den else None
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None


def probe_video(
    video_path: Path,
    ffprobe: Path,
    output_path: Path,
) -> dict[str, Any]:
    cmd = [
        str(ffprobe),
        "-v", "error",
        "-show_entries",
        "format=duration,format_name,bit_rate:"
        "stream=index,codec_type,codec_name,width,height,"
        "avg_frame_rate,r_frame_rate,sample_rate,channels",
        "-of", "json",
        str(video_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise StageError(
            "ffprobe 读取视频失败："
            + (proc.stderr.strip() or f"exit={proc.returncode}")
        )

    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise StageError("ffprobe 返回了无法解析的 JSON。") from exc

    streams = raw.get("streams", [])
    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (s for s in streams if s.get("codec_type") == "audio"),
        None,
    )

    if video_stream is None:
        raise StageError("输入文件中未发现视频流。")

    try:
        duration = float(raw.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise StageError("无法获得有效视频时长。")

    metadata = {
        "schema_version": "1.0",
        "duration": duration,
        "format_name": raw.get("format", {}).get("format_name"),
        "bit_rate": raw.get("format", {}).get("bit_rate"),
        "video": {
            "codec": video_stream.get("codec_name"),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "avg_frame_rate": _parse_rate(video_stream.get("avg_frame_rate")),
            "r_frame_rate": _parse_rate(video_stream.get("r_frame_rate")),
        },
        "audio": None,
    }

    if audio_stream is not None:
        metadata["audio"] = {
            "codec": audio_stream.get("codec_name"),
            "sample_rate": audio_stream.get("sample_rate"),
            "channels": audio_stream.get("channels"),
        }

    atomic_write_json(output_path, metadata)
    return metadata
