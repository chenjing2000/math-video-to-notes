from __future__ import annotations

import subprocess
from pathlib import Path

from ..errors import StageError


def extract_audio(
    *,
    video_path: Path,
    ffmpeg: Path,
    output_path: Path,
    sample_rate: int = 16000,
    channels: int = 1,
    codec: str = "pcm_s16le",
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(video_path),
        "-vn",
        "-ac", str(channels),
        "-ar", str(sample_rate),
        "-acodec", codec,
        str(output_path),
        "-y",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise StageError(
            "音频提取失败："
            + (proc.stderr.strip() or f"exit={proc.returncode}")
        )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise StageError("ffmpeg 未生成有效音频文件。")

    return output_path
