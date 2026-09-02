import pytest

from video_to_notes.errors import StageError
from video_to_notes.reconstruction.validation import (
    validate_chunk,
    validate_lecture_draft,
)


def test_reject_unknown_evidence_id():
    data = {
        "topics": [
            {
                "title": "知识点",
                "content": "内容",
                "origin": "video",
                "evidence_ids": ["ev_missing"],
                "status": "confirmed",
            }
        ],
        "problems": [],
        "section_hints": [],
    }
    with pytest.raises(StageError):
        validate_chunk(data, {"ev_0001"})


def test_reject_supplement_in_reconstruction():
    lecture = {
        "schema_version": "1.0",
        "stage": "reconstruction_draft",
        "metadata": {},
        "overview": {},
        "sections": [],
        "problems": [],
        "supplements": [{"content": "不允许"}],
    }
    with pytest.raises(StageError):
        validate_lecture_draft(lecture, {"ev_0001"})
