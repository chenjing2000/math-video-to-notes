from pathlib import Path

from video_to_notes.audit.checks import (
    audit_content,
    audit_evidence,
    audit_review,
    audit_supplements,
    audit_latex,
)


def test_audit_evidence_detects_unknown_and_conflict():
    lecture = {
        "sections": [{
            "id": "sec_01",
            "blocks": [{
                "id": "blk_01",
                "content": "x",
                "origin": "video",
                "status": "confirmed",
                "evidence_ids": ["ev_missing"],
            }],
        }],
        "problems": [],
        "supplements": [],
    }
    timeline = {
        "timeline": [{
            "id": "ev_0001",
            "status": "conflict",
            "frame_ids": [],
        }]
    }

    result = audit_evidence(lecture, timeline)
    codes = {x["code"] for x in result["issues"]}
    assert "unknown_evidence_id" in codes
    assert "unresolved_evidence_conflict" in codes


def test_audit_content_detects_problem_without_statement():
    lecture = {
        "sections": [],
        "problems": [{"id": "P01", "statement": None}],
        "supplements": [],
    }
    result = audit_content(lecture)
    assert any(x["code"] == "problem_missing_statement" for x in result["issues"])


def test_audit_supplement_detects_bad_target():
    lecture = {
        "sections": [{"id": "sec_01", "blocks": []}],
        "problems": [],
        "supplements": [{
            "id": "sup_001",
            "target_id": "P99",
            "reason": "missing_content",
            "why_needed": "needed",
            "content": "x",
            "origin": "supplement",
        }],
    }
    result = audit_supplements(lecture)
    assert any(x["code"] == "supplement_unknown_target" for x in result["issues"])


def test_audit_review_blocks_open_teacher_error():
    lecture = {
        "review": {
            "issues": [{
                "id": "rv_001",
                "target_id": "P01.teacher_answer",
                "review_type": "math",
                "severity": "warning",
                "status": "open",
                "label": "possible_teacher_error",
                "message": "x",
                "source_value": "48°",
                "review_value": "46°",
            }]
        }
    }
    result = audit_review(lecture)
    assert result["metrics"]["open_possible_teacher_errors"] == 1
    assert any(x["code"] == "open_possible_teacher_error" for x in result["issues"])


def test_audit_latex_passes_clean_report(tmp_path):
    (tmp_path / "latex").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / "latex" / "lecture.tex").write_text("x", encoding="utf-8")
    (tmp_path / "output" / "lecture.pdf").write_bytes(b"pdf")

    result = audit_latex(
        render_report={
            "runs": 2,
            "missing_images": [],
            "latex_metrics": {
                "latex_errors": 0,
                "undefined_control_sequence": 0,
                "missing_characters": 0,
                "overfull_hbox": 1,
            },
        },
        workspace_root=tmp_path,
    )
    assert result["issues"] == []
    assert result["metrics"]["overfull_hbox"] == 1
