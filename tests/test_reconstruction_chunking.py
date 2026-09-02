from video_to_notes.reconstruction.chunking import chunk_evidence


def test_chunk_evidence_preserves_order():
    timeline = [
        {"id": f"ev_{i:04d}", "text": "x" * 80}
        for i in range(8)
    ]
    chunks = chunk_evidence(timeline, max_chars=250)
    flattened = [item["id"] for chunk in chunks for item in chunk]
    assert flattened == [f"ev_{i:04d}" for i in range(8)]
    assert len(chunks) > 1
