from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..errors import StageError
from ..stages import StageContext
from ..util import atomic_write_json, read_json
from .builder import build_evidence_timeline


def _load_required_json(path: Path, description: str) -> dict[str, Any]:
    if not path.exists():
        raise StageError(
            f"缺少 {description}: {path}。请先运行前置 stage。"
        )
    try:
        data = read_json(path)
    except Exception as exc:
        raise StageError(f"无法读取 {description}: {path}") from exc
    if not isinstance(data, dict):
        raise StageError(f"{description} 根节点必须为 object。")
    return data


def run_evidence_stage(ctx: StageContext) -> None:
    logger: logging.Logger = ctx.logger
    cfg = ctx.config["evidence"]

    visual_path = (
        ctx.workspace_root
        / "visual"
        / "segments"
        / "segments.json"
    )
    transcript_path = (
        ctx.workspace_root
        / "transcript"
        / "transcript.json"
    )

    visual_data = _load_required_json(
        visual_path,
        "Visual Segments",
    )
    transcript_data = _load_required_json(
        transcript_path,
        "Transcript",
    )

    visual_segments = visual_data.get("segments")
    transcript_segments = transcript_data.get("segments")

    if not isinstance(visual_segments, list) or not visual_segments:
        raise StageError("Visual Segments 为空。")
    if not isinstance(transcript_segments, list) or not transcript_segments:
        raise StageError("Transcript Segments 为空。")

    logger.info(
        "[evidence] aligning %d visual segments with %d transcript segments",
        len(visual_segments),
        len(transcript_segments),
    )

    timeline, orphans = build_evidence_timeline(
        visual_segments=visual_segments,
        transcript_segments=transcript_segments,
        config=cfg,
    )

    evidence_dir = ctx.workspace_root / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    output = {
        "schema_version": "1.0",
        "design": "visual_first",
        "timeline": timeline,
        "orphan_transcripts": (
            orphans
            if bool(cfg.get("include_orphan_transcripts", True))
            else []
        ),
    }
    atomic_write_json(
        evidence_dir / "timeline.json",
        output,
    )

    with_transcript = sum(
        1 for item in timeline if item["direct_transcript_ids"]
    )
    with_frames = sum(
        1 for item in timeline if item["frame_ids"]
    )
    confirmed = sum(
        1 for item in timeline if item["status"] == "confirmed"
    )
    probable = sum(
        1 for item in timeline if item["status"] == "probable"
    )
    uncertain = sum(
        1 for item in timeline if item["status"] == "uncertain"
    )

    report = {
        "schema_version": "1.0",
        "visual_segments": len(visual_segments),
        "transcript_segments": len(transcript_segments),
        "evidence_segments": len(timeline),
        "visual_segments_with_transcript": with_transcript,
        "visual_segments_with_frames": with_frames,
        "orphan_transcripts": len(orphans),
        "status": {
            "confirmed": confirmed,
            "probable": probable,
            "uncertain": uncertain,
        },
        "output": str(evidence_dir / "timeline.json"),
    }
    atomic_write_json(
        ctx.workspace_root / "reports" / "evidence_report.json",
        report,
    )

    logger.info(
        "[evidence] timeline=%d with_transcript=%d with_frames=%d "
        "orphans=%d",
        len(timeline),
        with_transcript,
        with_frames,
        len(orphans),
    )
