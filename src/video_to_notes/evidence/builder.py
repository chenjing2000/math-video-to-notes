from __future__ import annotations

from typing import Any

from .alignment import (
    compute_evidence_confidence,
    interval_overlap,
    select_transcripts_for_visual_segment,
    transcript_coverage_ratio,
)


def _status_from_confidence(
    confidence: float,
    *,
    has_visual: bool,
) -> str:
    if not has_visual:
        return "uncertain"
    if confidence >= 0.82:
        return "confirmed"
    if confidence >= 0.62:
        return "probable"
    return "uncertain"


def build_evidence_timeline(
    *,
    visual_segments: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    padding_before = float(config.get("transcript_padding_before", 1.5))
    padding_after = float(config.get("transcript_padding_after", 1.5))
    min_overlap = float(config.get("min_overlap_seconds", 0.05))

    confidence_cfg = config.get("confidence", {})
    visual_weight = float(confidence_cfg.get("visual_weight", 0.55))
    transcript_weight = float(confidence_cfg.get("transcript_weight", 0.45))

    timeline: list[dict[str, Any]] = []
    used_transcript_ids: set[str] = set()

    for idx, visual in enumerate(visual_segments):
        matched = select_transcripts_for_visual_segment(
            visual,
            transcript_segments,
            padding_before=padding_before,
            padding_after=padding_after,
            min_overlap_seconds=min_overlap,
        )

        clean_transcripts = []
        direct_transcripts = []
        for tr in matched:
            padded_overlap = tr.pop("_alignment_overlap_seconds", 0.0)
            direct_overlap = interval_overlap(
                float(visual["start"]),
                float(visual["end"]),
                float(tr["start"]),
                float(tr["end"]),
            )
            alignment_role = "direct" if direct_overlap > 0 else "context"

            tr_copy = {
                "id": tr["id"],
                "start": tr["start"],
                "end": tr["end"],
                "text": tr["text"],
                "alignment_role": alignment_role,
                "direct_overlap_seconds": round(direct_overlap, 6),
                "padded_overlap_seconds": padded_overlap,
            }
            if "avg_logprob" in tr:
                tr_copy["avg_logprob"] = tr["avg_logprob"]
            if "no_speech_prob" in tr:
                tr_copy["no_speech_prob"] = tr["no_speech_prob"]
            clean_transcripts.append(tr_copy)
            if alignment_role == "direct":
                direct_transcripts.append(tr)
            used_transcript_ids.add(str(tr["id"]))

        raw_coverage = transcript_coverage_ratio(
            float(visual["start"]),
            float(visual["end"]),
            direct_transcripts,
        )

        evidence_frames = visual.get("evidence_frames", [])
        has_visual = bool(evidence_frames) or bool(visual.get("scan_frame_ids"))
        visual_conf = float(visual.get("confidence", 0.5))

        confidence = compute_evidence_confidence(
            visual_confidence=visual_conf,
            transcript_coverage=raw_coverage,
            has_transcript=bool(direct_transcripts),
            visual_weight=visual_weight,
            transcript_weight=transcript_weight,
        )

        transcript_text = " ".join(
            str(tr["text"]).strip()
            for tr in clean_transcripts
            if str(tr["text"]).strip()
        )

        item = {
            "id": f"ev_{idx:04d}",
            "visual_segment_id": visual["id"],
            "start": visual["start"],
            "end": visual["end"],
            "visual_type": visual.get("visual_type", "unknown"),
            "frame_ids": [
                frame["id"]
                for frame in evidence_frames
            ],
            "frames": evidence_frames,
            "transcript_ids": [
                tr["id"]
                for tr in clean_transcripts
            ],
            "direct_transcript_ids": [
                tr["id"]
                for tr in clean_transcripts
                if tr["alignment_role"] == "direct"
            ],
            "context_transcript_ids": [
                tr["id"]
                for tr in clean_transcripts
                if tr["alignment_role"] == "context"
            ],
            "transcripts": clean_transcripts,
            "transcript_text": transcript_text,
            "transcript_coverage_ratio": round(raw_coverage, 6),
            "content_type": "unknown",
            "confidence": confidence,
            "status": _status_from_confidence(
                confidence,
                has_visual=has_visual,
            ),
        }
        timeline.append(item)

    orphans = [
        tr for tr in transcript_segments
        if str(tr["id"]) not in used_transcript_ids
    ]

    return timeline, orphans
