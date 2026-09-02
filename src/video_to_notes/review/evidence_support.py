from __future__ import annotations

from typing import Any


def collect_evidence_ids_from_targets(
    targets: list[dict[str, Any]],
) -> set[str]:
    result: set[str] = set()
    for target in targets:
        for eid in target.get("evidence_ids", []):
            result.add(str(eid))
    return result


def select_evidence(
    timeline: list[dict[str, Any]],
    *,
    evidence_ids: set[str],
) -> list[dict[str, Any]]:
    selected = []
    for item in timeline:
        if str(item.get("id")) not in evidence_ids:
            continue
        selected.append({
            "id": item.get("id"),
            "start": item.get("start"),
            "end": item.get("end"),
            "visual_type": item.get("visual_type"),
            "frame_ids": item.get("frame_ids", []),
            "transcript_text": item.get("transcript_text", ""),
            "confidence": item.get("confidence"),
            "status": item.get("status"),
        })
    return selected
