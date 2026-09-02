from video_to_notes.evidence.builder import build_evidence_timeline


def test_build_evidence_timeline():
    visual = [
        {
            "id": "vs_0000",
            "start": 0.0,
            "end": 10.0,
            "visual_type": "progressive_board",
            "confidence": 0.9,
            "scan_frame_ids": ["scan_0"],
            "evidence_frames": [
                {
                    "id": "evf_000000",
                    "time": 4.0,
                    "path": "frame.jpg",
                }
            ],
        },
        {
            "id": "vs_0001",
            "start": 10.0,
            "end": 20.0,
            "visual_type": "stable_slide",
            "confidence": 0.8,
            "scan_frame_ids": ["scan_1"],
            "evidence_frames": [],
        },
    ]

    transcripts = [
        {
            "id": "tr_000000",
            "start": 1.0,
            "end": 5.0,
            "text": "第一段",
        },
        {
            "id": "tr_000001",
            "start": 6.0,
            "end": 9.0,
            "text": "第二段",
        },
        {
            "id": "tr_000002",
            "start": 30.0,
            "end": 31.0,
            "text": "孤立字幕",
        },
    ]

    timeline, orphans = build_evidence_timeline(
        visual_segments=visual,
        transcript_segments=transcripts,
        config={
            "transcript_padding_before": 0.0,
            "transcript_padding_after": 0.0,
            "min_overlap_seconds": 0.05,
            "confidence": {
                "visual_weight": 0.55,
                "transcript_weight": 0.45,
            },
        },
    )

    assert len(timeline) == 2
    assert timeline[0]["visual_segment_id"] == "vs_0000"
    assert timeline[0]["transcript_ids"] == [
        "tr_000000",
        "tr_000001",
    ]
    assert timeline[0]["direct_transcript_ids"] == [
        "tr_000000",
        "tr_000001",
    ]
    assert timeline[0]["context_transcript_ids"] == []
    assert timeline[0]["frame_ids"] == ["evf_000000"]
    assert timeline[0]["transcript_text"] == "第一段 第二段"
    assert len(orphans) == 1
    assert orphans[0]["id"] == "tr_000002"
