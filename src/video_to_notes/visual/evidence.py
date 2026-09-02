from __future__ import annotations

from pathlib import Path
from typing import Any

from ..util import atomic_write_json
from .extract import extract_exact_frame
from .image_metrics import phash, hamming_distance


def _evenly_select(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return items[:]
    if limit == 1:
        return [items[len(items) // 2]]

    indexes = []
    for i in range(limit):
        idx = round(i * (len(items) - 1) / (limit - 1))
        if idx not in indexes:
            indexes.append(idx)
    return [items[i] for i in indexes]


def _dedup_stable(
    items: list[dict[str, Any]],
    *,
    max_frames: int,
    hash_distance: int = 7,
) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    chosen_hashes: list[int] = []

    for item in items:
        h = phash(Path(item["path"]))
        if any(hamming_distance(h, old) <= hash_distance for old in chosen_hashes):
            continue
        chosen.append(item)
        chosen_hashes.append(h)
        if len(chosen) >= max_frames:
            break

    if not chosen and items:
        return [items[0]]
    return chosen


def _progressive_candidates(
    segment: dict[str, Any],
    scan_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    frames = segment.get("candidate_frames", [])
    if not frames:
        return []

    selected_ids = {frames[0]["id"], frames[-1]["id"]}
    for transition in segment.get("transitions", []):
        if transition["transition"] == "incremental":
            selected_ids.add(transition["to_frame_id"])

    return [
        scan_by_id[frame_id]
        for frame_id in selected_ids
        if frame_id in scan_by_id
    ]


def select_and_extract_evidence_frames(
    *,
    video_path: Path,
    ffmpeg: Path,
    segments: list[dict[str, Any]],
    scan_frames: list[dict[str, Any]],
    output_dir: Path,
    cfg: dict,
    output_path: Path,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for p in output_dir.glob("evf_*.jpg"):
        p.unlink()

    scan_by_id = {f["id"]: f for f in scan_frames}
    all_evidence: list[dict[str, Any]] = []
    next_id = 0

    for segment in segments:
        items = sorted(
            segment.get("candidate_frames", []),
            key=lambda x: float(x["time"]),
        )
        visual_type = segment["visual_type"]

        if visual_type == "stable_slide":
            selected = _dedup_stable(
                items,
                max_frames=int(cfg["stable_max_frames"]),
            )
        elif visual_type == "progressive_board":
            selected = _evenly_select(
                sorted(
                    _progressive_candidates(segment, scan_by_id),
                    key=lambda x: float(x["time"]),
                ),
                int(cfg["progressive_max_frames"]),
            )
        elif visual_type == "dynamic_visual":
            selected = _evenly_select(
                items,
                int(cfg["dynamic_max_frames"]),
            )
        else:
            selected = _evenly_select(
                items,
                int(cfg["mixed_max_frames"]),
            )

        segment_evidence = []
        for item in selected:
            evidence_id = f"evf_{next_id:06d}"
            dst = output_dir / f"{evidence_id}.jpg"

            extract_exact_frame(
                video_path=video_path,
                ffmpeg=ffmpeg,
                time_seconds=float(item["time"]),
                output_path=dst,
                width=int(cfg["extraction_width"]),
                jpeg_quality=int(cfg["jpeg_quality"]),
            )

            record = {
                "id": evidence_id,
                "segment_id": segment["id"],
                "time": item["time"],
                "path": str(dst),
                "source_frame_id": item["id"],
                "source": "highres_exact",
            }
            next_id += 1
            segment_evidence.append(record)
            all_evidence.append(record)

        segment["evidence_frames"] = segment_evidence
        segment.pop("candidate_frames", None)

    atomic_write_json(output_path, {
        "schema_version": "1.0",
        "frames": all_evidence,
    })
    return all_evidence
