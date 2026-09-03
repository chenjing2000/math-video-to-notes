from copy import deepcopy

from video_to_notes.review.pedagogical_core import (
    PEDAGOGICAL_REPAIR_MODELS,
    apply_repair_round,
    assign_pedagogical_issue_ids,
    build_repair_context,
    repair_summary,
    validate_repair_response,
)


def _lecture():
    return {
        "sections": [{"id": "sec_01", "title": "角度关系", "blocks": []}],
        "problems": [{
            "id": "P01",
            "section_id": "sec_01",
            "statement": {"content": "完整题目：已知 A、B 两角关系，求 x。"},
            "teacher_solution": {"content": "老师原解：先作辅助线，再列角度关系。"},
            "derived_solution": {"content": "补充推导：第一步；第二步；第三步。"},
            "publication_solution": {
                "content": "当前出版解答：由角度关系得到 x=46^\\circ。",
                "source_kind": "derived_solution",
            },
            "teacher_answer": {"content": "46°"},
            "publication_answer": {"content": "$46^\\circ$"},
        }],
        "supplements": [{
            "id": "sup_001",
            "target_id": "P01",
            "type": "derived_solution",
            "content": "原始补充推导。",
        }],
        "summary": [],
    }


def test_repair_context_rereads_full_problem_and_current_solution():
    lecture = _lecture()
    context = build_repair_context(lecture, "P01.teacher_solution")
    problem = context["problem"]
    assert problem["statement"]["content"].startswith("完整题目")
    assert "当前出版解答" in problem["publication_solution"]["content"]
    assert "老师原解" in problem["teacher_solution"]["content"]
    assert "补充推导" in problem["derived_solution"]["content"]


def test_unresolved_repair_never_publishes_model_content():
    lecture = _lecture()
    original = deepcopy(lecture)
    issues = assign_pedagogical_issue_ids([{
        "target_id": "P01.teacher_solution",
        "review_type": "pedagogical",
        "severity": "warning",
        "label": "clarity",
        "message": "推导不够连续。",
        "status": "open",
    }])
    repairs = validate_repair_response({"repairs": [{
        "issue_id": "pg_001",
        "target_id": "P01.teacher_solution",
        "status": "unresolved",
        "action": "replace_target",
        "content": "这个文本不应进入讲义。",
    }]}, expected_issues=issues)
    result = apply_repair_round(
        lecture, issues, repairs, round_index=1, model=PEDAGOGICAL_REPAIR_MODELS[0]
    )
    assert result["resolved"] == []
    assert result["unresolved"] == ["pg_001"]
    assert lecture == original


def test_resolved_repair_changes_publication_layer_but_not_teacher_source():
    lecture = _lecture()
    teacher_solution = deepcopy(lecture["problems"][0]["teacher_solution"])
    issues = assign_pedagogical_issue_ids([{
        "target_id": "P01.teacher_solution",
        "review_type": "pedagogical",
        "severity": "warning",
        "label": "clarity",
        "message": "表述可更清楚。",
        "status": "open",
    }])
    repairs = validate_repair_response({"repairs": [{
        "issue_id": "pg_001",
        "target_id": "P01.teacher_solution",
        "status": "resolved",
        "action": "replace_target",
        "content": "讲义层修复后的完整推导。",
    }]}, expected_issues=issues)
    apply_repair_round(
        lecture, issues, repairs, round_index=1, model=PEDAGOGICAL_REPAIR_MODELS[0]
    )
    assert lecture["problems"][0]["teacher_solution"] == teacher_solution
    assert lecture["problems"][0]["publication_solution"]["content"] == "讲义层修复后的完整推导。"
    assert lecture["problems"][0]["publication_solution"]["source_kind"] == "derived_solution"
    summary = repair_summary(issues, [{"round": 1}])
    assert summary["resolved"] == 1
    assert summary["unresolved"] == 0
    assert summary["complete_with_unresolved"] is False


def test_repair_route_is_fixed_to_three_rounds():
    from video_to_notes.review.pedagogical_core import (
        PEDAGOGICAL_REPAIR_ROUTE,
        REPAIR_RESOLVED,
        REPAIR_UNRESOLVED_NON_BLOCKING,
        next_repair_model,
        repair_model,
    )

    assert PEDAGOGICAL_REPAIR_ROUTE == ("terra-xhigh", "sol-medium", "sol-high")
    assert repair_model(1) == "terra-xhigh"
    assert repair_model(2) == "sol-medium"
    assert repair_model(3) == "sol-high"
    assert repair_model(4) is None
    assert next_repair_model(1, REPAIR_RESOLVED) is None
    assert next_repair_model(1, REPAIR_UNRESOLVED_NON_BLOCKING) == "sol-medium"
    assert next_repair_model(3, REPAIR_UNRESOLVED_NON_BLOCKING) is None


def test_repair_round_is_atomic_when_one_mutation_is_impossible():
    lecture = _lecture()
    original = deepcopy(lecture)
    issues = assign_pedagogical_issue_ids([
        {
            "target_id": "P01.teacher_solution",
            "review_type": "pedagogical",
            "severity": "warning",
            "label": "clarity",
            "message": "需要改写。",
            "status": "open",
        },
        {
            "target_id": "P01.unknown_publication_target",
            "review_type": "pedagogical",
            "severity": "warning",
            "label": "clarity",
            "message": "非法 target 用于原子性测试。",
            "status": "open",
        },
    ])
    repairs = validate_repair_response(
        {
            "repairs": [
                {
                    "issue_id": "pg_001",
                    "target_id": "P01.teacher_solution",
                    "status": "resolved",
                    "action": "replace_target",
                    "content": "本应写入，但同批次另一动作失败，因此不得提交。",
                },
                {
                    "issue_id": "pg_002",
                    "target_id": "P01.unknown_publication_target",
                    "status": "resolved",
                    "action": "replace_target",
                    "content": "无法应用。",
                },
            ]
        },
        expected_issues=issues,
    )

    result = apply_repair_round(
        lecture,
        issues,
        repairs,
        round_index=1,
        model="terra-xhigh",
    )
    assert result["status"] == "invalid"
    assert lecture == original
    assert all(issue["status"] == "open" for issue in issues)


def test_repair_round_is_idempotent_for_same_in_memory_issue_state():
    lecture = _lecture()
    issues = assign_pedagogical_issue_ids([
        {
            "target_id": "P01.teacher_solution",
            "review_type": "pedagogical",
            "severity": "warning",
            "label": "clarity",
            "message": "增加补充。",
            "status": "open",
        }
    ])
    repairs = validate_repair_response(
        {
            "repairs": [
                {
                    "issue_id": "pg_001",
                    "target_id": "P01.teacher_solution",
                    "status": "resolved",
                    "action": "append_supplement",
                    "content": "唯一补充内容。",
                }
            ]
        },
        expected_issues=issues,
    )

    first = apply_repair_round(
        lecture, issues, repairs, round_index=1, model="terra-xhigh"
    )
    second = apply_repair_round(
        lecture, issues, repairs, round_index=1, model="terra-xhigh"
    )
    matching = [x for x in lecture["supplements"] if x.get("id") == "sup_pg_001"]
    assert len(matching) == 1
    assert first["applied"] == 1
    assert second["applied"] == 0
    assert second["already_applied"] == ["pg_001"]
    assert second["status"] == "resolved"


def test_invalid_business_response_consumes_round_without_mutation():
    from video_to_notes.review.pedagogical_core import REPAIR_INVALID

    lecture = _lecture()
    original = deepcopy(lecture)
    issues = assign_pedagogical_issue_ids([
        {
            "target_id": "P01.teacher_solution",
            "review_type": "pedagogical",
            "severity": "warning",
            "label": "clarity",
            "message": "需要修复。",
            "status": "open",
        }
    ])
    result = apply_repair_round(
        lecture,
        issues,
        [],
        round_index=1,
        model="terra-xhigh",
        invalid_issue_ids=["pg_001"],
    )
    assert result["status"] == REPAIR_INVALID
    assert result["invalid_issue_ids"] == ["pg_001"]
    assert lecture == original
    assert issues[0]["status"] == "open"
