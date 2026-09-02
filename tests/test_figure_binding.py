from pathlib import Path

from video_to_notes.reconstruction.figures import bind_problem_figures, statement_needs_figure


def test_bind_problem_figure_from_statement_evidence(tmp_path: Path):
    frame = tmp_path / "visual" / "evidence_frames" / "evf_000001.jpg"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"jpg")

    lecture = {
        "problems": [{
            "id": "P01",
            "statement": {
                "content": "如图，在三角形 ABC 中，D 为 BC 的中点。",
                "evidence_ids": ["ev_0001"],
            },
            "figure_evidence_ids": [],
        }],
        "figures": [],
    }
    timeline = [{
        "id": "ev_0001",
        "visual_type": "stable_slide",
        "frames": [{"id": "evf_000001", "time": 12.5, "path": str(frame)}],
    }]

    report = bind_problem_figures(lecture, timeline, workspace_root=tmp_path)
    assert report["figures_bound"] == 1
    assert lecture["problems"][0]["figure_evidence_ids"] == ["ev_0001"]
    fig = lecture["figures"][0]
    assert fig["problem_id"] == "P01"
    assert fig["frame_id"] == "evf_000001"
    assert fig["evidence_path"].endswith("visual/evidence_frames/evf_000001.jpg")


def test_geometry_problem_can_require_figure_without_literal_ru_tu():
    problem = {
        "statement": {
            "content": "在三角形 ABC 中，CE 是 AB 边上的中线，延长 CE 至 P。"
        }
    }
    assert statement_needs_figure(problem) is True
