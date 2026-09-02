from video_to_notes.render.context import build_render_context


def test_build_render_context():
    lecture = {
        "sections": [{"id": "sec_01", "title": "A", "blocks": []}],
        "problems": [
            {"id": "P01", "section_id": "sec_01"},
            {"id": "P02"},
        ],
        "supplements": [
            {"id": "sup_001", "target_id": "P01", "content": "x"}
        ],
        "figures": [
            {"id": "fig_001", "problem_id": "P01"}
        ],
        "review": {
            "issues": [
                {"id": "rv_001", "target_id": "P01", "message": "m"}
            ]
        },
    }

    ctx = build_render_context(lecture)
    assert ctx["problems_by_section"]["sec_01"][0]["id"] == "P01"
    assert ctx["unassigned_problems"][0]["id"] == "P02"
    assert ctx["supplements_by_target"]["P01"][0]["id"] == "sup_001"
    assert ctx["figures_by_problem"]["P01"][0]["id"] == "fig_001"
    assert ctx["issues_by_target"]["P01"][0]["id"] == "rv_001"
