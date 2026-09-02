import pytest

from video_to_notes.review.validation import (
    assign_issue_ids,
    validate_raw_issues,
)


def test_validate_review_issue():
    issues = validate_raw_issues(
        [{
            "target_id": "P01.teacher_answer",
            "severity": "warning",
            "label": "possible_teacher_error",
            "message": "答案疑似有误。",
            "source_value": "48°",
            "review_value": "46°",
        }],
        review_type="math",
        valid_target_ids={"P01.teacher_answer"},
    )

    assert issues[0]["review_type"] == "math"
    assert issues[0]["status"] == "open"
    assert issues[0]["source_value"] == "48°"

    numbered = assign_issue_ids(issues)
    assert numbered[0]["id"] == "rv_001"


def test_reject_unknown_review_target():
    with pytest.raises(Exception):
        validate_raw_issues(
            [{
                "target_id": "P99",
                "severity": "warning",
                "label": "other",
                "message": "x",
            }],
            review_type="factual",
            valid_target_ids={"P01"},
        )


def test_reject_bad_severity():
    with pytest.raises(Exception):
        validate_raw_issues(
            [{
                "target_id": "P01",
                "severity": "critical",
                "label": "other",
                "message": "x",
            }],
            review_type="math",
            valid_target_ids={"P01"},
        )
