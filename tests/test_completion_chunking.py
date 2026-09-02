from video_to_notes.completion.chunking import make_completion_chunks


def test_completion_chunking():
    lecture = {
        "sections": [{"id": "sec_01"}, {"id": "sec_02"}],
        "problems": [{"id": "P01"}, {"id": "P02"}],
    }

    chunks = make_completion_chunks(
        lecture,
        max_items_per_call=2,
    )

    assert len(chunks) == 2
    assert len(chunks[0]["items"]) == 2
    assert len(chunks[1]["items"]) == 2
