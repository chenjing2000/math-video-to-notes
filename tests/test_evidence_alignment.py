from video_to_notes.evidence.alignment import (
    interval_overlap,
    transcript_coverage_ratio,
    select_transcripts_for_visual_segment,
)


def test_interval_overlap():
    assert interval_overlap(0, 10, 5, 15) == 5
    assert interval_overlap(0, 10, 10, 20) == 0
    assert interval_overlap(0, 10, 2, 4) == 2


def test_select_transcripts_with_padding():
    visual = {"start": 10.0, "end": 20.0}
    transcripts = [
        {"id": "a", "start": 8.8, "end": 10.2, "text": "A"},
        {"id": "b", "start": 12.0, "end": 14.0, "text": "B"},
        {"id": "c", "start": 21.2, "end": 22.0, "text": "C"},
        {"id": "d", "start": 30.0, "end": 31.0, "text": "D"},
    ]

    result = select_transcripts_for_visual_segment(
        visual,
        transcripts,
        padding_before=1.5,
        padding_after=1.5,
        min_overlap_seconds=0.05,
    )

    assert [x["id"] for x in result] == ["a", "b", "c"]


def test_transcript_coverage_ratio():
    transcripts = [
        {"start": 0.0, "end": 2.0},
        {"start": 3.0, "end": 5.0},
    ]
    ratio = transcript_coverage_ratio(0.0, 10.0, transcripts)
    assert ratio == 0.4
