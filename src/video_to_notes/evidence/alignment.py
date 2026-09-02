from __future__ import annotations

from typing import Any


def interval_overlap(
    a_start: float,
    a_end: float,
    b_start: float,
    b_end: float,
) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def transcript_coverage_ratio(
    segment_start: float,
    segment_end: float,
    transcripts: list[dict[str, Any]],
) -> float:
    duration = max(0.0, segment_end - segment_start)
    if duration <= 0:
        return 0.0

    intervals: list[tuple[float, float]] = []
    for tr in transcripts:
        start = max(segment_start, float(tr["start"]))
        end = min(segment_end, float(tr["end"]))
        if end > start:
            intervals.append((start, end))

    if not intervals:
        return 0.0

    intervals.sort()
    merged: list[list[float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)

    covered = sum(end - start for start, end in merged)
    return min(1.0, covered / duration)


def select_transcripts_for_visual_segment(
    visual_segment: dict[str, Any],
    transcript_segments: list[dict[str, Any]],
    *,
    padding_before: float,
    padding_after: float,
    min_overlap_seconds: float,
) -> list[dict[str, Any]]:
    start = float(visual_segment["start"]) - max(0.0, padding_before)
    end = float(visual_segment["end"]) + max(0.0, padding_after)

    selected = []
    for tr in transcript_segments:
        overlap = interval_overlap(
            start,
            end,
            float(tr["start"]),
            float(tr["end"]),
        )
        if overlap >= min_overlap_seconds:
            item = dict(tr)
            item["_alignment_overlap_seconds"] = round(overlap, 6)
            selected.append(item)

    return selected


def compute_evidence_confidence(
    *,
    visual_confidence: float,
    transcript_coverage: float,
    has_transcript: bool,
    visual_weight: float,
    transcript_weight: float,
) -> float:
    vw = max(0.0, visual_weight)
    tw = max(0.0, transcript_weight)

    if not has_transcript:
        # Absence of speech is not necessarily an error; visual evidence remains valid.
        return round(max(0.0, min(1.0, visual_confidence * 0.9)), 3)

    total = vw + tw
    if total <= 0:
        return round(max(0.0, min(1.0, visual_confidence)), 3)

    score = (
        vw * visual_confidence
        + tw * transcript_coverage
    ) / total
    return round(max(0.0, min(1.0, score)), 3)
