from video_to_notes.audit.checks import audit_figures, audit_problem_completeness


def _problem():
    return {
        "id": "P03",
        "statement": {
            "content": "如图，求证：CD=2CE。",
            "evidence_ids": ["ev_0010"],
        },
        "teacher_solution": {
            "content": "延长 CE 至 P，使 EP=CE；后续证明未完整呈现。",
            "status": "confirmed",
        },
        "teacher_answer": {"content": "CD=2CE"},
    }


def test_audit_blocks_missing_figure_and_missing_derived_solution():
    lecture = {"problems": [_problem()], "figures": [], "supplements": []}
    fig = audit_figures(lecture)
    comp = audit_problem_completeness(lecture)
    assert any(x["code"] == "problem_missing_required_figure" for x in fig["issues"])
    assert any(x["code"] == "incomplete_problem_without_derived_solution" for x in comp["issues"])


def test_audit_accepts_bound_figure_and_verified_derived_solution():
    lecture = {
        "problems": [_problem()],
        "figures": [{"id": "fig_P03_01", "problem_id": "P03", "evidence_path": "x.jpg"}],
        "supplements": [{
            "id": "sup_001",
            "target_id": "P03",
            "reason": "incomplete_explanation",
            "type": "derived_solution",
            "why_needed": "老师未讲完证明。",
            "content": "完整证明",
            "origin": "supplement",
            "status": "confirmed",
            "math_review_status": "verified",
        }],
    }
    assert audit_figures(lecture)["issues"] == []
    assert audit_problem_completeness(lecture)["issues"] == []
