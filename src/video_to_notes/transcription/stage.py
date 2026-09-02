from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..errors import StageError
from ..stages import StageContext
from ..util import atomic_write_json, read_json
from ..visual.tools import resolve_ffmpeg_pair
from .audio import extract_audio
from .formatting import (
    write_transcript_json,
    write_transcript_srt,
    write_transcript_txt,
)
from .whisper_engine import transcribe_audio


def _source_path(workspace_root: Path) -> Path:
    project = read_json(workspace_root / "project.json")
    path = Path(project["source"]["workspace_path"])
    if not path.exists():
        path = Path(project["source"]["original_path"])
    return path


def run_transcription_stage(ctx: StageContext) -> None:
    cfg = ctx.config
    logger: logging.Logger = ctx.logger
    transcription_cfg: dict[str, Any] = cfg["transcription"]

    ffmpeg, _ = resolve_ffmpeg_pair(cfg)
    video_path = _source_path(ctx.workspace_root)

    transcript_dir = ctx.workspace_root / "transcript"
    transcript_dir.mkdir(parents=True, exist_ok=True)

    audio_cfg = transcription_cfg["audio"]
    whisper_cfg = transcription_cfg["whisper"]
    output_cfg = transcription_cfg["output"]

    audio_path = transcript_dir / "audio.wav"

    logger.info("[transcription] extracting audio")
    extract_audio(
        video_path=video_path,
        ffmpeg=ffmpeg,
        output_path=audio_path,
        sample_rate=int(audio_cfg["sample_rate"]),
        channels=int(audio_cfg["channels"]),
        codec=str(audio_cfg["codec"]),
    )

    logger.info(
        "[transcription] whisper model=%s language=%s",
        whisper_cfg.get("model"),
        whisper_cfg.get("language"),
    )
    result = transcribe_audio(
        audio_path,
        config=whisper_cfg,
    )

    if not result.segments:
        raise StageError("Whisper 未返回任何有效转录片段。")

    if bool(output_cfg.get("write_json", True)):
        write_transcript_json(
            transcript_dir / "transcript.json",
            metadata=result.metadata,
            segments=result.segments,
        )

    if bool(output_cfg.get("write_srt", True)):
        write_transcript_srt(
            transcript_dir / "transcript.srt",
            result.segments,
        )

    if bool(output_cfg.get("write_txt", True)):
        write_transcript_txt(
            transcript_dir / "transcript.txt",
            result.segments,
        )

    total_text_chars = sum(len(seg["text"]) for seg in result.segments)
    covered_start = min(float(seg["start"]) for seg in result.segments)
    covered_end = max(float(seg["end"]) for seg in result.segments)

    report = {
        "schema_version": "1.0",
        "segments": len(result.segments),
        "characters": total_text_chars,
        "coverage": {
            "start": covered_start,
            "end": covered_end,
        },
        "metadata": result.metadata,
        "outputs": {
            "audio": str(audio_path),
            "json": str(transcript_dir / "transcript.json"),
            "srt": str(transcript_dir / "transcript.srt"),
            "txt": str(transcript_dir / "transcript.txt"),
        },
    }
    atomic_write_json(
        ctx.workspace_root / "reports" / "transcription_report.json",
        report,
    )

    logger.info(
        "[transcription] segments=%d characters=%d",
        len(result.segments),
        total_text_chars,
    )
