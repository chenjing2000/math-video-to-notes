import pytest

from video_to_notes.errors import StageError
from video_to_notes.review.math_core import (
    apply_math_review_cascade,
    collect_math_review_targets,
    filter_target_for_ids,
    unresolved_target_ids,
    validate_math_revision_response,
)


def _lecture():
    return {
        "problems": [{
            "id": "P01",
            "statement": {"content": "求证 $A=B$", "evidence_ids": ["ev_1"]},
            "teacher_solution": {"content": "原始老师解法", "evidence_ids": ["ev_2"]},
            "teacher_answer": {"content": "$A=B$", "evidence_ids": ["ev_3"]},
        }],
        "supplements": [{
            "id": "sup_001",
            "target_id": "P01",
            "type": "derived_solution",
            "content": "原始补充推导",
            "status": "probable",
            "math_review_status": "pending",
        }],
    }


def test_math_review_requires_every_solution_process():
    targets = collect_math_review_targets(_lecture())
    with pytest.raises(StageError, match="漏审 target_id"):
        validate_math_revision_response({
            "reviewed_solutions": [{
                "target_id": "P01.teacher_solution",
                "status": "verified",
            }],
            "reviewed_answers": [{
                "target_id": "P01.teacher_answer",
                "status": "verified",
            }],
        }, targets)


def test_verified_does_not_need_or_rewrite_content():
    lecture = _lecture()
    targets = collect_math_review_targets(lecture)
    medium = validate_math_revision_response({
        "reviewed_solutions": [
            {"target_id": "P01.teacher_solution", "status": "verified"},
            {"target_id": "sup_001", "status": "verified"},
        ],
        "reviewed_answers": [{"target_id": "P01.teacher_answer", "status": "verified"}],
    }, targets)
    summary = apply_math_review_cascade(lecture, targets, medium_results={"P01": medium}, high_results={})
    problem = lecture["problems"][0]
    assert problem["teacher_solution"]["content"] == "原始老师解法"
    assert problem["publication_solution"]["content"] == "原始老师解法"
    assert problem["publication_answer"]["content"] == "$A=B$"
    assert summary["verified"] == 3
    assert summary["complete_with_unresolved"] is False


def test_revised_content_is_published_but_source_is_preserved():
    lecture = _lecture()
    targets = collect_math_review_targets(lecture)
    medium = validate_math_revision_response({
        "reviewed_solutions": [
            {"target_id": "P01.teacher_solution", "status": "revised", "content": "Sol 修正后的解法"},
            {"target_id": "sup_001", "status": "verified"},
        ],
        "reviewed_answers": [
            {"target_id": "P01.teacher_answer", "status": "revised", "content": "$A=C$"},
        ],
    }, targets)
    summary = apply_math_review_cascade(lecture, targets, medium_results={"P01": medium}, high_results={})
    problem = lecture["problems"][0]
    assert problem["teacher_solution"]["content"] == "原始老师解法"
    assert problem["publication_solution"]["content"] == "Sol 修正后的解法"
    assert problem["teacher_answer"]["content"] == "$A=B$"
    assert problem["publication_answer"]["content"] == "$A=C$"
    assert lecture["supplements"][0]["content"] == "原始补充推导"
    assert summary["revised"] == 2


def test_only_medium_unresolved_targets_are_sent_to_high_and_high_unresolved_text_is_ignored():
    lecture = _lecture()
    targets = collect_math_review_targets(lecture)
    target = targets[0]
    medium = validate_math_revision_response({
        "reviewed_solutions": [
            {"target_id": "P01.teacher_solution", "status": "verified"},
            {"target_id": "sup_001", "status": "unresolved", "content": "不可信猜测"},
        ],
        "reviewed_answers": [{"target_id": "P01.teacher_answer", "status": "verified"}],
    }, targets)
    unresolved = unresolved_target_ids(medium)
    assert unresolved == {"sup_001"}
    high_target = filter_target_for_ids(target, unresolved)
    assert [x["target_id"] for x in high_target["solutions"]] == ["sup_001"]
    assert high_target["answer"] is None
    high = validate_math_revision_response({
        "reviewed_solutions": [{"target_id": "sup_001", "status": "unresolved", "content": "仍然猜测"}],
        "reviewed_answers": [],
    }, [high_target])
    summary = apply_math_review_cascade(
        lecture, targets, medium_results={"P01": medium}, high_results={"P01": high}
    )
    problem = lecture["problems"][0]
    assert problem["math_review_unresolved"] is True
    assert "不可信猜测" not in str(problem)
    assert "仍然猜测" not in str(problem)
    assert summary["complete"] is True
    assert summary["complete_with_unresolved"] is True
