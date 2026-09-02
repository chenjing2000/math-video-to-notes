from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..stages import StageContext
from ..util import atomic_write_json, read_json
from .evidence import select_and_extract_evidence_frames
from .extract import (
    extract_coverage_frames,
    extract_scan_frames,
    extract_scene_frames,
)
from .probe import probe_video
from .segments import build_segments
from .tools import resolve_ffmpeg_pair


def _source_path(workspace_root: Path) -> Path:
    project = read_json(workspace_root / "project.json")
    path = Path(project["source"]["workspace_path"])
    if not path.exists():
        path = Path(project["source"]["original_path"])
    return path


def run_visual_stage(ctx: StageContext) -> None:
    cfg = ctx.config
    logger: logging.Logger = ctx.logger
    visual_cfg: dict[str, Any] = cfg["visual"]

    ffmpeg, ffprobe = resolve_ffmpeg_pair(cfg)
    video_path = _source_path(ctx.workspace_root)

    source_dir = ctx.workspace_root / "source"
    visual_dir = ctx.workspace_root / "visual"
    coverage_dir = visual_dir / "coverage"
    scan_dir = visual_dir / "scan"
    scene_dir = visual_dir / "scene"
    segments_dir = visual_dir / "segments"
    evidence_dir = visual_dir / "evidence_frames"

    logger.info("[visual] ffmpeg: %s", ffmpeg)
    logger.info("[visual] ffprobe: %s", ffprobe)

    metadata = probe_video(
        video_path,
        ffprobe,
        source_dir / "video_info.json",
    )
    duration = float(metadata["duration"])
    logger.info(
        "[visual] duration %.2fs, %sx%s",
        duration,
        metadata["video"]["width"],
        metadata["video"]["height"],
    )

    coverage = extract_coverage_frames(
        video_path=video_path,
        ffmpeg=ffmpeg,
        output_dir=coverage_dir,
        duration=duration,
        interval=float(visual_cfg["coverage_interval"]),
        width=int(visual_cfg["extraction_width"]),
        jpeg_quality=int(visual_cfg["jpeg_quality"]),
    )
    logger.info("[visual] coverage frames: %d", len(coverage))

    scan_cfg = visual_cfg["scan"]
    if bool(scan_cfg.get("enabled", True)):
        scan_frames = extract_scan_frames(
            video_path=video_path,
            ffmpeg=ffmpeg,
            output_dir=scan_dir,
            duration=duration,
            interval=float(scan_cfg["interval"]),
            width=int(scan_cfg["width"]),
            jpeg_quality=int(scan_cfg["jpeg_quality"]),
        )
    else:
        scan_frames = coverage
    logger.info("[visual] scan frames: %d", len(scan_frames))

    scene_cfg = visual_cfg["scene"]
    if bool(scene_cfg.get("enabled", True)):
        scenes = extract_scene_frames(
            video_path=video_path,
            ffmpeg=ffmpeg,
            output_dir=scene_dir,
            threshold=float(scene_cfg["threshold"]),
            min_gap_seconds=float(scene_cfg["min_gap_seconds"]),
            width=int(visual_cfg["extraction_width"]),
            jpeg_quality=int(visual_cfg["jpeg_quality"]),
        )
    else:
        scenes = []
        atomic_write_json(scene_dir / "scene_events.json", {
            "schema_version": "1.0",
            "events": [],
        })
    logger.info("[visual] scene events: %d", len(scenes))

    segments = build_segments(
        duration=duration,
        scan_frames=scan_frames,
        coverage_frames=coverage,
        scene_events=scenes,
        transition_cfg=visual_cfg["transition"],
        classification_cfg=visual_cfg["classification"],
        output_path=segments_dir / "segments.json",
    )

    counts: dict[str, int] = {}
    for seg in segments:
        counts[seg["visual_type"]] = counts.get(seg["visual_type"], 0) + 1
    logger.info("[visual] segments: %d %s", len(segments), counts)

    evidence_frames = select_and_extract_evidence_frames(
        video_path=video_path,
        ffmpeg=ffmpeg,
        segments=segments,
        scan_frames=scan_frames,
        output_dir=evidence_dir,
        cfg=visual_cfg["evidence"],
        output_path=evidence_dir / "evidence_frames.json",
    )
    logger.info("[visual] evidence frames: %d", len(evidence_frames))

    atomic_write_json(segments_dir / "segments.json", {
        "schema_version": "1.0",
        "duration": duration,
        "segments": segments,
    })

    report = {
        "schema_version": "1.0",
        "duration": duration,
        "coverage_frames": len(coverage),
        "scan_frames": len(scan_frames),
        "scene_events": len(scenes),
        "segments": len(segments),
        "segment_types": counts,
        "evidence_frames": len(evidence_frames),
        "outputs": {
            "video_info": str(source_dir / "video_info.json"),
            "coverage": str(coverage_dir / "coverage.json"),
            "scan": str(scan_dir / "scan.json"),
            "scene_events": str(scene_dir / "scene_events.json"),
            "segments": str(segments_dir / "segments.json"),
            "evidence_frames": str(
                evidence_dir / "evidence_frames.json"
            ),
        },
    }
    atomic_write_json(
        ctx.workspace_root / "reports" / "visual_report.json",
        report,
    )
