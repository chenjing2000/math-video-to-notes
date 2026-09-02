from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def _run(project_root: Path, env: dict[str, str], *args: str):
    return subprocess.run(
        [sys.executable, "-m", "video_to_notes", *args],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )


def test_sprint10_rerun_completion_from_rendered_and_verify_derived_solution(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake")
    workspace_root = tmp_path / "workspace"
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "project": {
            "workspace_root": str(workspace_root),
            "project_root": str(project_root),
        },
        "llm": {"mode": "codex_handoff"},
    }, allow_unicode=True), encoding="utf-8")

    assert _run(project_root, env, "--config", str(config), "init", str(video)).returncode == 0
    ws = workspace_root / "lesson"
    (ws / "lecture").mkdir(parents=True, exist_ok=True)
    (ws / "evidence").mkdir(parents=True, exist_ok=True)

    teacher_solution = "延长 CE 至 P，使 EP=CE，并连接 BP；分块证据未完整呈现后续证明。"
    lecture = {
        "schema_version": "1.0",
        "stage": "rendered",
        "metadata": {},
        "overview": {},
        "sections": [],
        "problems": [{
            "id": "P03",
            "title": "例题 3",
            "statement": {
                "content": "在三角形 ABC 中，CE 是 AB 边上的中线，求证：CD=2CE。",
                "origin": "video",
                "evidence_ids": ["ev_0010"],
                "status": "confirmed",
            },
            "teacher_solution": {
                "content": teacher_solution,
                "origin": "video",
                "evidence_ids": ["ev_0011"],
                "status": "confirmed",
            },
            "teacher_answer": {
                "content": "CD=2CE",
                "origin": "video",
                "evidence_ids": ["ev_0012"],
                "status": "confirmed",
            },
        }],
        "supplements": [],
        "figures": [],
        "summary": [],
        "review": {"issues": []},
    }
    (ws / "lecture" / "lecture.json").write_text(json.dumps(lecture, ensure_ascii=False), encoding="utf-8")
    (ws / "evidence" / "timeline.json").write_text(json.dumps({"timeline": [
        {"id": "ev_0010", "start": 0, "end": 5, "frames": [], "frame_ids": [], "status": "confirmed"},
        {"id": "ev_0011", "start": 5, "end": 10, "frames": [], "frame_ids": [], "status": "confirmed"},
        {"id": "ev_0012", "start": 10, "end": 12, "frames": [], "frame_ids": [], "status": "confirmed"},
    ]}, ensure_ascii=False), encoding="utf-8")

    prep = _run(project_root, env, "--config", str(config), "complete", "prepare", str(video))
    assert prep.returncode == 0, prep.stderr
    task = json.loads((ws / "tasks" / "completion" / "chunk_0000.request.json").read_text(encoding="utf-8"))
    assert task["required_model"] == "terra"
    assert '"solution_completeness": "incomplete"' in task["user"]

    response = {
        "request_id": task["request_id"],
        "items": [{
            "target_id": "P03",
            "reason": "incomplete_explanation",
            "type": "derived_solution",
            "why_needed": "老师后续证明未完整呈现。",
            "derivation_basis": ["题目条件", "老师构造 CE=EP"],
            "content": "由题目条件继续严格推导，最终得到 $CD=2CE$。",
        }]
    }
    responses = ws / "responses" / "completion"
    responses.mkdir(parents=True, exist_ok=True)
    (responses / "chunk_0000.json").write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    (responses / "completion.json").write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")

    applied = _run(project_root, env, "--config", str(config), "complete", "apply", str(video))
    assert applied.returncode == 0, applied.stderr
    completed = json.loads((ws / "lecture" / "lecture.json").read_text(encoding="utf-8"))
    assert completed["problems"][0]["teacher_solution"]["content"] == teacher_solution
    assert completed["supplements"][0]["type"] == "derived_solution"
    assert completed["supplements"][0]["math_review_status"] == "pending"

    prep_review = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
    assert prep_review.returncode == 0, prep_review.stderr
    math_task = json.loads((ws / "tasks" / "review" / "math.request.json").read_text(encoding="utf-8"))
    assert math_task["required_model"] == "sol"
    assert "sup_001" in math_task["user"]

    manifest = json.loads((ws / "tasks" / "review" / "manifest.json").read_text(encoding="utf-8"))
    review_responses = ws / "responses" / "review"
    review_responses.mkdir(parents=True, exist_ok=True)
    for name in manifest["required_outputs"]:
        payload = {"request_id": manifest["request_id"], "issues": []}
        if name == "math.json":
            payload["verified_supplements"] = ["sup_001"]
        (review_responses / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    applied_review = _run(project_root, env, "--config", str(config), "review", "apply", str(video))
    assert applied_review.returncode == 0, applied_review.stderr
    reviewed = json.loads((ws / "lecture" / "lecture.json").read_text(encoding="utf-8"))
    assert reviewed["supplements"][0]["math_review_status"] == "verified"
    assert reviewed["supplements"][0]["status"] == "confirmed"
