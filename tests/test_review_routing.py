from video_to_notes.review.routing import (
    collect_all_target_ids,
    collect_factual_targets,
)
from video_to_notes.review.math_core import collect_math_review_targets


def _lecture():
    return {
        "sections": [
            {
                "id": "sec_01",
                "blocks": [
                    {
                        "id": "blk_001",
                        "type": "knowledge",
                        "content": "a=b",
                        "origin": "video",
                        "status": "probable",
                        "evidence_ids": ["ev_0001"],
                    }
                ],
            }
        ],
        "problems": [
            {
                "id": "P01",
                "statement": {
                    "content": "求 x",
                    "origin": "video",
                    "status": "confirmed",
                    "evidence_ids": ["ev_0002"],
                },
                "teacher_solution": {
                    "content": "x=2",
                    "origin": "video",
                    "status": "confirmed",
                    "evidence_ids": ["ev_0003"],
                },
                "teacher_answer": {
                    "content": "2",
                    "origin": "video",
                    "status": "confirmed",
                    "evidence_ids": ["ev_0004"],
                },
            }
        ],
        "supplements": [
            {
                "id": "sup_001",
                "target_id": "P01",
                "origin": "supplement",
            }
        ],
    }


def test_collect_all_target_ids():
    ids = collect_all_target_ids(_lecture())
    assert {
        "lecture",
        "sec_01",
        "blk_001",
        "P01",
        "P01.statement",
        "P01.teacher_solution",
        "P01.teacher_answer",
        "sup_001",
    }.issubset(ids)


def test_factual_router_reviews_important_problem_fields_and_uncertain_blocks():
    targets = collect_factual_targets(
        _lecture(),
        trigger_statuses={"probable", "uncertain", "conflict"},
        always_review_problem_fields={
            "statement",
            "teacher_solution",
            "teacher_answer",
        },
    )
    ids = {x["target_id"] for x in targets}
    assert "blk_001" in ids
    assert "P01.statement" in ids
    assert "P01.teacher_solution" in ids
    assert "P01.teacher_answer" in ids


def test_math_review_collects_every_solution_process():
    lecture = _lecture()
    lecture["supplements"][0].update({
        "type": "derived_solution",
        "content": "补充证明",
    })
    targets = collect_math_review_targets(lecture)
    assert len(targets) == 1
    target = targets[0]
    assert target["target_id"] == "P01"
    ids = {item["target_id"] for item in target["solutions"]}
    assert ids == {"P01.teacher_solution", "sup_001"}
    assert target["answer"]["target_id"] == "P01.teacher_answer"
