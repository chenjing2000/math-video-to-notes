import json
import logging

from video_to_notes.audit.stage import run_audit_stage
from video_to_notes.stages import StageContext


def test_audit_pass_with_notes_when_review_has_nonblocking_math_unresolved(tmp_path):
    ws = tmp_path / "ws"
    (ws / "lecture").mkdir(parents=True)
    (ws / "reports").mkdir(parents=True)
    (ws / "lecture" / "lecture.json").write_text(
        json.dumps({"stage": "rendered", "problems": []}, ensure_ascii=False), encoding="utf-8"
    )
    for name, payload in {
        "completion_report.json": {"quality": {"complete": True}},
        "review_report.json": {
            "quality": {
                "complete": True,
                "has_notes": True,
                "notes": [{"type": "math_unresolved"}],
            }
        },
        "render_report.json": {"quality": {"complete": True}},
    }.items():
        (ws / "reports" / name).write_text(json.dumps(payload), encoding="utf-8")

    run_audit_stage(
        StageContext(stage="audit", workspace_root=ws, config={}, logger=logging.getLogger("test"))
    )
    report = json.loads((ws / "reports/quality_report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "PASS_WITH_NOTES"
