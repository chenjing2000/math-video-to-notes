from __future__ import annotations

from statistics import mean
from pathlib import Path
from typing import Any

from ..util import atomic_write_json
from .image_metrics import compare_images


def _transition_kind(
    *,
    change_ratio: float,
    phash_distance: int,
    cfg: dict,
) -> str:
    if (
        change_ratio <= float(cfg["duplicate_change_ratio"])
        and phash_distance <= int(cfg["duplicate_phash_distance"])
    ):
        return "duplicate"

    if (
        change_ratio <= float(cfg["incremental_change_ratio"])
        and phash_distance <= int(cfg["incremental_phash_distance"])
    ):
        return "incremental"

    return "major"


def annotate_scan_transitions(
    *,
    scan_frames: list[dict[str, Any]],
    cfg: dict,
) -> list[dict[str, Any]]:
    transitions: list[dict[str, Any]] = []

    for previous, current in zip(scan_frames, scan_frames[1:]):
        metrics = compare_images(
            Path(previous["path"]),
            Path(current["path"]),
            pixel_threshold=int(cfg["pixel_difference_threshold"]),
        )
        transitions.append({
            "id": f"trv_{len(transitions):06d}",
            "time": current["time"],
            "from_frame_id": previous["id"],
            "to_frame_id": current["id"],
            "change_ratio": round(float(metrics["change_ratio"]), 6),
            "phash_distance": int(metrics["phash_distance"]),
            "transition": _transition_kind(
                change_ratio=float(metrics["change_ratio"]),
                phash_distance=int(metrics["phash_distance"]),
                cfg=cfg,
            ),
        })

    return transitions


def _in_range(time: float, start: float, end: float, is_last: bool) -> bool:
    return start <= time <= end if is_last else start <= time < end


def build_segments(
    *,
    duration: float,
    scan_frames: list[dict[str, Any]],
    coverage_frames: list[dict[str, Any]],
    scene_events: list[dict[str, Any]],
    transition_cfg: dict,
    classification_cfg: dict,
    output_path: Path,
) -> list[dict[str, Any]]:
    transitions = annotate_scan_transitions(
        scan_frames=scan_frames,
        cfg=transition_cfg,
    )

    major_times = [
        float(t["time"])
        for t in transitions
        if t["transition"] == "major"
        and 0.0 < float(t["time"]) < duration
    ]
    boundaries = [0.0] + sorted(set(major_times)) + [duration]

    segments: list[dict[str, Any]] = []

    for idx in range(len(boundaries) - 1):
        start = boundaries[idx]
        end = boundaries[idx + 1]
        is_last = idx == len(boundaries) - 2

        seg_transitions = [
            t for t in transitions
            if _in_range(float(t["time"]), start, end, is_last)
            and t["transition"] != "major"
        ]
        seg_scan = [
            f for f in scan_frames
            if _in_range(float(f["time"]), start, end, is_last)
        ]
        seg_coverage = [
            f for f in coverage_frames
            if _in_range(float(f["time"]), start, end, is_last)
        ]
        seg_scene = [
            f for f in scene_events
            if _in_range(float(f["time"]), start, end, is_last)
        ]

        incremental = [
            t for t in seg_transitions
            if t["transition"] == "incremental"
        ]
        meaningful = [
            t for t in seg_transitions
            if t["transition"] != "duplicate"
        ]

        segment_duration = max(0.001, end - start)
        event_rate = len(meaningful) * 60.0 / segment_duration
        ratios = [float(t["change_ratio"]) for t in meaningful]
        mean_ratio = mean(ratios) if ratios else 0.0

        progressive_min = int(
            classification_cfg["progressive_min_incremental_events"]
        )
        dynamic_rate = float(classification_cfg["dynamic_events_per_minute"])
        dynamic_ratio = float(
            classification_cfg["dynamic_min_mean_change_ratio"]
        )

        if len(incremental) >= progressive_min:
            visual_type = "progressive_board"
            confidence = min(0.98, 0.72 + 0.06 * len(incremental))
        elif event_rate >= dynamic_rate and mean_ratio >= dynamic_ratio:
            visual_type = "dynamic_visual"
            confidence = min(0.95, 0.68 + 0.02 * len(meaningful))
        else:
            visual_type = "stable_slide"
            confidence = 0.80 if seg_scan else 0.62

        segment = {
            "id": f"vs_{idx:04d}",
            "start": round(start, 6),
            "end": round(end, 6),
            "duration": round(segment_duration, 6),
            "visual_type": visual_type,
            "confidence": round(confidence, 3),
            "event_rate_per_minute": round(event_rate, 3),
            "mean_change_ratio": round(mean_ratio, 6),
            "scan_frame_ids": [f["id"] for f in seg_scan],
            "coverage_frame_ids": [f["id"] for f in seg_coverage],
            "scene_event_ids": [f["id"] for f in seg_scene],
            "transitions": seg_transitions,
            "candidate_frames": seg_scan,
            "evidence_frames": [],
        }
        segments.append(segment)

    atomic_write_json(output_path, {
        "schema_version": "1.0",
        "duration": duration,
        "segments": segments,
        "scan_transitions": transitions,
        "scene_events": scene_events,
    })
    return segments
