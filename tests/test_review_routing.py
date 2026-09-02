from video_to_notes.review.routing import (
    collect_all_target_ids,
    collect_factual_targets,
    collect_math_targets,
)


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


def test_math_router_reviews_problems():
    targets = collect_math_targets(
        _lecture(),
        review_all_problems=True,
    )
    ids = {x["target_id"] for x in targets}
    assert "P01" in ids
    assert "blk_001" in ids


def test_math_router_includes_problem_supplements():
    lecture = _lecture()
    lecture["supplements"][0].update({
        "type": "derived_solution",
        "content": "补充证明",
    })
    targets = collect_math_targets(lecture, review_all_problems=True)
    problem_target = next(x for x in targets if x["target_id"] == "P01")
    supplements = problem_target["content"]["supplements"]
    assert supplements[0]["id"] == "sup_001"
    assert supplements[0]["type"] == "derived_solution"
