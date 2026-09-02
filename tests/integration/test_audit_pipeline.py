import json
import os
import subprocess
import sys
from pathlib import Path


def _run(args, cwd, env):
    return subprocess.run(
        [sys.executable, "-m", "video_to_notes", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def _base_lecture():
    return {
        "schema_version": "1.0",
        "stage": "rendered",
        "metadata": {"title": "测试"},
        "overview": {},
        "sections": [{
            "id": "sec_01",
            "title": "第一节",
            "blocks": [{
                "id": "blk_001",
                "type": "knowledge",
                "content": "知识",
                "origin": "video",
                "status": "confirmed",
                "evidence_ids": ["ev_0001"],
            }],
        }],
        "problems": [{
            "id": "P01",
            "section_id": "sec_01",
            "statement": {
                "content": "题目",
                "origin": "video",
                "status": "confirmed",
                "evidence_ids": ["ev_0001"],
            },
            "teacher_solution": {
                "content": "解答",
                "origin": "video",
                "status": "confirmed",
                "evidence_ids": ["ev_0001"],
            },
            "teacher_answer": {
                "content": "2",
                "origin": "video",
                "status": "confirmed",
                "evidence_ids": ["ev_0001"],
            },
        }],
        "supplements": [],
        "figures": [],
        "summary": [],
        "review": {"issues": []},
    }



def _write_quality_contracts(ws: Path, *, review_ok: bool) -> None:
    (ws / "reports" / "completion_report.json").write_text(
        json.dumps({"quality": {"complete": True}}), encoding="utf-8"
    )
    (ws / "reports" / "review_report.json").write_text(
        json.dumps({"quality": {"complete": review_ok}}), encoding="utf-8"
    )
    render = json.loads((ws / "reports" / "render_report.json").read_text(encoding="utf-8"))
    render["quality"] = {"complete": True}
    (ws / "reports" / "render_report.json").write_text(json.dumps(render), encoding="utf-8")
    (ws / "stages").mkdir(parents=True, exist_ok=True)
    (ws / "stages" / "render.receipt.json").write_text(json.dumps({"receipt_id": "render-test", "status": "done"}), encoding="utf-8")

def test_audit_cli_pipeline_pass(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake")
    workspace_root = tmp_path / "workspace"

    config = tmp_path / "config.yaml"
    config.write_text(
        f'''project:\n  workspace_root: "{workspace_root.as_posix()}"\n''',
        encoding="utf-8",
    )

    init = _run(["--config", str(config), "init", str(video)], project_root, env)
    assert init.returncode == 0, init.stderr

    ws = workspace_root / "lesson"
    (ws / "lecture").mkdir(parents=True, exist_ok=True)
    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    (ws / "latex").mkdir(parents=True, exist_ok=True)
    (ws / "output").mkdir(parents=True, exist_ok=True)
    (ws / "reports").mkdir(parents=True, exist_ok=True)

    (ws / "lecture" / "lecture.json").write_text(
        json.dumps(_base_lecture(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ws / "evidence" / "timeline.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "timeline": [{
                "id": "ev_0001",
                "status": "confirmed",
                "frame_ids": ["evf_0001"],
            }],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ws / "latex" / "lecture.tex").write_text("test", encoding="utf-8")
    (ws / "output" / "lecture.pdf").write_bytes(b"fake-pdf")
    (ws / "reports" / "render_report.json").write_text(
        json.dumps({
            "runs": 2,
            "missing_images": [],
            "latex_metrics": {
                "latex_errors": 0,
                "undefined_control_sequence": 0,
                "missing_characters": 0,
                "overfull_hbox": 0,
            },
        }),
        encoding="utf-8",
    )
    _write_quality_contracts(ws, review_ok=True)

    result = _run(["--config", str(config), "audit", str(video)], project_root, env)
    assert result.returncode == 0, result.stderr

    report = json.loads(
        (ws / "reports" / "quality_report.json").read_text(encoding="utf-8")
    )
    assert report["verdict"] == "PASS"
    assert report["summary"]["failed"] == 0
    assert (ws / "reports" / "quality_report.md").exists()

    lecture = json.loads(
        (ws / "lecture" / "lecture.json").read_text(encoding="utf-8")
    )
    assert lecture["stage"] == "audited"
    assert lecture["audit"]["verdict"] == "PASS"


def test_audit_cli_pipeline_review_required(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake")
    workspace_root = tmp_path / "workspace"
    config = tmp_path / "config.yaml"
    config.write_text(
        f'''project:\n  workspace_root: "{workspace_root.as_posix()}"\n''',
        encoding="utf-8",
    )
    init = _run(["--config", str(config), "init", str(video)], project_root, env)
    assert init.returncode == 0

    ws = workspace_root / "lesson"
    for rel in ["lecture", "evidence", "latex", "output", "reports"]:
        (ws / rel).mkdir(parents=True, exist_ok=True)

    lecture = _base_lecture()
    lecture["review"]["issues"] = [{
        "id": "rv_001",
        "target_id": "P01.teacher_answer",
        "review_type": "math",
        "severity": "warning",
        "status": "open",
        "label": "possible_teacher_error",
        "message": "老师答案疑似错误",
        "source_value": "48°",
        "review_value": "46°",
    }]

    (ws / "lecture" / "lecture.json").write_text(
        json.dumps(lecture, ensure_ascii=False), encoding="utf-8"
    )
    (ws / "evidence" / "timeline.json").write_text(
        json.dumps({"timeline": [{
            "id": "ev_0001",
            "status": "confirmed",
            "frame_ids": ["evf_0001"],
        }]}), encoding="utf-8"
    )
    (ws / "latex" / "lecture.tex").write_text("x", encoding="utf-8")
    (ws / "output" / "lecture.pdf").write_bytes(b"pdf")
    (ws / "reports" / "render_report.json").write_text(
        json.dumps({
            "runs": 2,
            "missing_images": [],
            "latex_metrics": {
                "latex_errors": 0,
                "undefined_control_sequence": 0,
                "missing_characters": 0,
                "overfull_hbox": 0,
            },
        }), encoding="utf-8"
    )
    _write_quality_contracts(ws, review_ok=False)

    result = _run(["--config", str(config), "audit", str(video)], project_root, env)
    assert result.returncode == 0, result.stderr

    report = json.loads(
        (ws / "reports" / "quality_report.json").read_text(encoding="utf-8")
    )
    assert report["verdict"] == "REVIEW_REQUIRED"
    assert any(check["name"] == "review" and not check["passed"] for check in report["checks"])
