import pytest

from video_to_notes.completion.validation import (
    collect_valid_targets,
    validate_completion_items,
)


def test_collect_valid_targets():
    lecture = {
        "sections": [
            {
                "id": "sec_01",
                "blocks": [{"id": "blk_001"}],
            }
        ],
        "problems": [{"id": "P01"}],
    }

    assert collect_valid_targets(lecture) == {
        "sec_01",
        "blk_001",
        "P01",
    }


def test_validate_completion_items_marks_supplement():
    result = validate_completion_items(
        [{
            "target_id": "P01",
            "reason": "incomplete_explanation",
            "why_needed": "缺少关键推导。",
            "content": "由条件可得……",
        }],
        valid_targets={"P01"},
    )

    assert result == [{
        "id": "sup_001",
        "target_id": "P01",
        "reason": "incomplete_explanation",
        "why_needed": "缺少关键推导。",
        "content": "由条件可得……",
        "origin": "supplement",
        "status": "confirmed",
    }]


def test_reject_invalid_reason():
    with pytest.raises(Exception):
        validate_completion_items(
            [{
                "target_id": "P01",
                "reason": "extra_background",
                "why_needed": "x",
                "content": "y",
            }],
            valid_targets={"P01"},
        )


def test_reject_unknown_target():
    with pytest.raises(Exception):
        validate_completion_items(
            [{
                "target_id": "P99",
                "reason": "missing_content",
                "why_needed": "x",
                "content": "y",
            }],
            valid_targets={"P01"},
        )
