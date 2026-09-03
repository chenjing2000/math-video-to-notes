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


def _config(tmp_path: Path, project_root: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "project": {
                    "workspace_root": str(tmp_path / "workspace"),
                    "copy_source_video": False,
                    "project_root": str(project_root),
                },
                "llm": {"mode": "codex_handoff"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


def test_codex_handoff_reconstruction_prepare_apply(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake-video")
    config = _config(tmp_path, project_root)

    init = _run(project_root, env, "--config", str(config), "init", str(video))
    assert init.returncode == 0, init.stderr
    ws = tmp_path / "workspace" / "lesson"
    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    (ws / "evidence" / "timeline.json").write_text(
        json.dumps({
            "timeline": [{
                "id": "ev_0000", "start": 0.0, "end": 10.0,
                "visual_type": "stable_slide", "frame_ids": ["evf_000000"],
                "transcript_text": "定义内容", "confidence": 0.9, "status": "confirmed",
            }]
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    prep = _run(project_root, env, "--config", str(config), "reconstruct", "prepare", str(video))
    assert prep.returncode == 0, prep.stderr
    task_dir = ws / "tasks" / "reconstruction"
    assert (task_dir / "INSTRUCTIONS.md").exists()
    assert (task_dir / "chunk_0000.request.json").exists()
    assert (task_dir / "merge.request.json").exists()
    chunk_task = json.loads((task_dir / "chunk_0000.request.json").read_text(encoding="utf-8"))
    merge_task = json.loads((task_dir / "merge.request.json").read_text(encoding="utf-8"))
    assert chunk_task["required_model"] == "terra"
    assert merge_task["required_model"] == "terra"
    chunk_rid = chunk_task["request_id"]
    merge_rid = merge_task["request_id"]

    responses = ws / "responses" / "reconstruction"
    responses.mkdir(parents=True, exist_ok=True)
    (responses / "chunk_0000.json").write_text(json.dumps({
        "request_id": chunk_rid,
        "topics": [{
            "title": "定义", "content": "定义内容", "origin": "video",
            "evidence_ids": ["ev_0000"], "status": "confirmed",
        }],
        "problems": [],
        "section_hints": [{"title": "第一节", "evidence_ids": ["ev_0000"]}],
    }, ensure_ascii=False), encoding="utf-8")
    (responses / "lecture.json").write_text(json.dumps({
        "request_id": merge_rid,
        "schema_version": "1.0",
        "stage": "reconstruction_draft",
        "metadata": {},
        "overview": {"topic": "测试", "main_line": "定义", "core_methods": [], "learning_objectives": []},
        "sections": [{
            "id": "sec_01", "title": "第一节", "type": "concept",
            "source_ranges": [[0.0, 10.0]], "evidence_ids": ["ev_0000"],
            "blocks": [{
                "id": "blk_001", "type": "definition", "content": "定义内容",
                "origin": "video", "evidence_ids": ["ev_0000"], "status": "confirmed",
            }],
        }],
        "problems": [], "supplements": [], "figures": [], "summary": [],
        "review": {"issues": []},
    }, ensure_ascii=False), encoding="utf-8")

    apply = _run(project_root, env, "--config", str(config), "reconstruct", "apply", str(video))
    assert apply.returncode == 0, apply.stderr
    lecture = json.loads((ws / "lecture" / "lecture.json").read_text(encoding="utf-8"))
    assert lecture["stage"] == "reconstruction_draft"
    assert lecture["sections"][0]["evidence_ids"] == ["ev_0000"]


def test_codex_handoff_completion_and_review_apply(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake-video")
    config = _config(tmp_path, project_root)
    assert _run(project_root, env, "--config", str(config), "init", str(video)).returncode == 0
    ws = tmp_path / "workspace" / "lesson"
    (ws / "lecture").mkdir(parents=True, exist_ok=True)
    (ws / "evidence").mkdir(parents=True, exist_ok=True)

    lecture = {
        "schema_version": "1.0", "stage": "reconstruction_draft", "metadata": {}, "overview": {},
        "sections": [{"id": "sec_01", "title": "角度", "blocks": [], "evidence_ids": ["ev_0001"]}],
        "problems": [{
            "id": "P01", "section_id": "sec_01", "title": "例题",
            "statement": {"content": "求角", "origin": "video", "evidence_ids": ["ev_0001"], "status": "confirmed"},
            "teacher_solution": {"content": "推导", "origin": "video", "evidence_ids": ["ev_0002"], "status": "confirmed"},
            "teacher_answer": {"content": "48°", "origin": "video", "evidence_ids": ["ev_0003"], "status": "confirmed"},
        }],
        "supplements": [], "figures": [], "summary": [], "review": {"issues": []},
    }
    (ws / "lecture" / "lecture.json").write_text(json.dumps(lecture, ensure_ascii=False), encoding="utf-8")
    (ws / "evidence" / "timeline.json").write_text(json.dumps({"timeline": [
        {"id": "ev_0001", "start": 0, "end": 5, "visual_type": "stable_slide", "frame_ids": [], "transcript_text": "求角", "confidence": .9, "status": "confirmed"},
        {"id": "ev_0002", "start": 5, "end": 10, "visual_type": "progressive_board", "frame_ids": [], "transcript_text": "推导", "confidence": .9, "status": "confirmed"},
        {"id": "ev_0003", "start": 10, "end": 12, "visual_type": "progressive_board", "frame_ids": [], "transcript_text": "四十八度", "confidence": .9, "status": "confirmed"},
    ]}, ensure_ascii=False), encoding="utf-8")

    prep = _run(project_root, env, "--config", str(config), "complete", "prepare", str(video))
    assert prep.returncode == 0, prep.stderr
    cmanifest = json.loads((ws / "tasks" / "completion" / "manifest.json").read_text(encoding="utf-8"))
    cchunk = json.loads((ws / "tasks" / "completion" / "chunk_0000.request.json").read_text(encoding="utf-8"))
    cmerge = json.loads((ws / "tasks" / "completion" / "merge.request.json").read_text(encoding="utf-8"))
    crid = cchunk["request_id"]
    cmerge_rid = cmerge["request_id"]
    cresp = ws / "responses" / "completion"
    cresp.mkdir(parents=True, exist_ok=True)
    item = {"target_id": "P01", "reason": "pedagogical_bridge", "why_needed": "补足一步", "content": "先建立对应关系。"}
    (cresp / "chunk_0000.json").write_text(json.dumps({"request_id": crid, "items": [item]}, ensure_ascii=False), encoding="utf-8")
    (cresp / "completion.json").write_text(json.dumps({"request_id": cmerge_rid, "items": [item]}, ensure_ascii=False), encoding="utf-8")
    applied = _run(project_root, env, "--config", str(config), "complete", "apply", str(video))
    assert applied.returncode == 0, applied.stderr

    # Review is phased: factual -> per-problem Sol Medium -> optional Sol High -> pedagogical.
    prep = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
    assert prep.returncode == 0, prep.stderr
    review_tasks = ws / "tasks" / "review"
    rresp = ws / "responses" / "review"
    rresp.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((review_tasks / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "factual"
    factual_task = json.loads((review_tasks / "factual.request.json").read_text(encoding="utf-8"))
    assert factual_task["required_model"] == "luna-high"
    (rresp / "factual.json").write_text(json.dumps({"request_id": factual_task["request_id"], "issues": []}, ensure_ascii=False), encoding="utf-8")

    prep = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
    assert prep.returncode == 0, prep.stderr
    manifest = json.loads((review_tasks / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "math_medium"
    math_name = "math_P01_medium.json"
    math_task = json.loads((review_tasks / "math_P01_medium.request.json").read_text(encoding="utf-8"))
    assert math_task["required_model"] == "sol-medium"
    (rresp / math_name).write_text(json.dumps({
        "request_id": math_task["request_id"],
        "reviewed_solutions": [{
            "target_id": "P01.teacher_solution", "status": "revised",
            "content": "由正确的角度关系推导，得到 $46^\\circ$。",
        }],
        "reviewed_answers": [{
            "target_id": "P01.teacher_answer", "status": "revised", "content": "$46^\\circ$",
        }],
    }, ensure_ascii=False), encoding="utf-8")

    prep = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
    assert prep.returncode == 0, prep.stderr
    manifest = json.loads((review_tasks / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "pedagogical"
    pedagogical_task = json.loads((review_tasks / "pedagogical.request.json").read_text(encoding="utf-8"))
    assert pedagogical_task["required_model"] == "terra"
    (rresp / "pedagogical.json").write_text(json.dumps({"request_id": pedagogical_task["request_id"], "issues": []}, ensure_ascii=False), encoding="utf-8")

    prep = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
    assert prep.returncode == 0, prep.stderr
    manifest = json.loads((review_tasks / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "ready"

    applied = _run(project_root, env, "--config", str(config), "review", "apply", str(video))
    assert applied.returncode == 0, applied.stderr
    reviewed = json.loads((ws / "lecture" / "lecture.json").read_text(encoding="utf-8"))
    assert reviewed["stage"] == "review_draft"
    assert reviewed["problems"][0]["teacher_answer"]["content"] == "48°"
    assert reviewed["problems"][0]["publication_answer"]["content"] == "$46^\\circ$"
    assert reviewed["problems"][0]["publication_solution"]["review_status"] == "revised"
    assert reviewed["review"]["issues"] == []


def test_codex_tasks_status(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy(); env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"; video.write_bytes(b"fake")
    config = _config(tmp_path, project_root)
    assert _run(project_root, env, "--config", str(config), "init", str(video)).returncode == 0
    result = _run(project_root, env, "--config", str(config), "codex-tasks", str(video))
    assert result.returncode == 0
    assert "reconstruction" in result.stdout
    assert "no prepared task" in result.stdout


def test_pedagogical_repair_escalates_three_rounds_then_continues_with_notes(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake-video")
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "project": {
            "workspace_root": str(tmp_path / "workspace"),
            "copy_source_video": False,
            "project_root": str(project_root),
        },
        "llm": {"mode": "codex_handoff"},
        "review": {
            "factual": {"enabled": False},
            "math": {"enabled": False},
            "pedagogical": {
                "enabled": True,
                "whole_lecture": True,
                "repair": {"enabled": True},
            },
        },
    }, allow_unicode=True), encoding="utf-8")
    assert _run(project_root, env, "--config", str(config), "init", str(video)).returncode == 0

    ws = tmp_path / "workspace" / "lesson"
    (ws / "lecture").mkdir(parents=True, exist_ok=True)
    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    lecture = {
        "schema_version": "1.0",
        "stage": "completion_draft",
        "metadata": {}, "overview": {},
        "sections": [{"id": "sec_01", "title": "角度", "blocks": []}],
        "problems": [{
            "id": "P01", "section_id": "sec_01", "title": "例题",
            "statement": {"content": "完整题目：已知两个角的关系，求 x。", "origin": "video", "evidence_ids": [], "status": "confirmed"},
            "teacher_solution": {"content": "老师原解。", "origin": "video", "evidence_ids": [], "status": "confirmed"},
            "derived_solution": {"content": "补充推导的完整链条。", "origin": "supplement", "evidence_ids": [], "status": "confirmed"},
            "publication_solution": {"content": "当前讲义解答：由关系得到 x=46°。", "source_kind": "derived_solution", "review_status": "verified"},
            "teacher_answer": {"content": "46°", "origin": "video", "evidence_ids": [], "status": "confirmed"},
            "publication_answer": {"content": "46°", "review_status": "verified"},
        }],
        "supplements": [], "figures": [], "summary": [], "review": {"issues": []},
    }
    (ws / "lecture" / "lecture.json").write_text(json.dumps(lecture, ensure_ascii=False), encoding="utf-8")
    (ws / "evidence" / "timeline.json").write_text(json.dumps({"timeline": []}), encoding="utf-8")

    tasks = ws / "tasks" / "review"
    responses = ws / "responses" / "review"
    responses.mkdir(parents=True, exist_ok=True)

    # Initial pedagogical review.
    prep = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
    assert prep.returncode == 0, prep.stderr
    manifest = json.loads((tasks / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "pedagogical"
    ped_req = json.loads((tasks / "pedagogical.request.json").read_text(encoding="utf-8"))
    (responses / "pedagogical.json").write_text(json.dumps({
        "request_id": ped_req["request_id"],
        "issues": [{
            "target_id": "P01.teacher_solution",
            "severity": "warning",
            "label": "clarity",
            "message": "当前讲义推导还不够连续。",
            "source_value": None,
            "review_value": None,
        }],
    }, ensure_ascii=False), encoding="utf-8")

    expected_models = ["terra-xhigh", "sol-medium", "sol-high"]
    for round_index, expected_model in enumerate(expected_models, start=1):
        prep = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
        assert prep.returncode == 0, prep.stderr
        manifest = json.loads((tasks / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["phase"] == f"pedagogical_repair_{round_index}"
        name = f"ped_repair_r{round_index}_P01.teacher_solution"
        req = json.loads((tasks / f"{name}.request.json").read_text(encoding="utf-8"))
        assert req["required_model"] == expected_model
        # Every escalation must reread the full problem and the current publication solution.
        assert "完整题目：已知两个角的关系，求 x。" in req["user"]
        assert "当前讲义解答：由关系得到 x=46°。" in req["user"]
        assert "老师原解。" in req["user"]
        assert "补充推导的完整链条。" in req["user"]
        (responses / f"{name}.json").write_text(json.dumps({
            "request_id": req["request_id"],
            "repairs": [{
                "issue_id": "pg_001",
                "target_id": "P01.teacher_solution",
                "status": "unresolved",
                "action": "keep",
                "content": "",
            }],
        }, ensure_ascii=False), encoding="utf-8")

    # Third unresolved response is terminal for repair, but not for the pipeline.
    prep = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
    assert prep.returncode == 0, prep.stderr
    manifest = json.loads((tasks / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "ready"
    assert manifest["pedagogical_repair_models"] == expected_models

    applied = _run(project_root, env, "--config", str(config), "review", "apply", str(video))
    assert applied.returncode == 0, applied.stderr
    reviewed = json.loads((ws / "lecture" / "lecture.json").read_text(encoding="utf-8"))
    assert reviewed["stage"] == "review_draft"
    assert reviewed["problems"][0]["teacher_solution"]["content"] == "老师原解。"
    assert reviewed["problems"][0]["publication_solution"]["content"] == "当前讲义解答：由关系得到 x=46°。"
    assert reviewed["review"]["pedagogical_repair"]["unresolved"] == 1
    assert reviewed["review"]["pedagogical_repair"]["complete_with_unresolved"] is True
    report = json.loads((ws / "reports" / "review_report.json").read_text(encoding="utf-8"))
    assert report["quality"]["complete"] is True
    assert report["quality"]["has_notes"] is True
    assert report["quality"]["notes"][0]["type"] == "pedagogical_unresolved"


def test_pedagogical_repair_stops_after_first_resolved_round(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy(); env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"; video.write_bytes(b"fake")
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "project": {"workspace_root": str(tmp_path / "workspace"), "project_root": str(project_root)},
        "llm": {"mode": "codex_handoff"},
        "review": {
            "factual": {"enabled": False}, "math": {"enabled": False},
            "pedagogical": {"enabled": True, "whole_lecture": True, "repair": {"enabled": True}},
        },
    }, allow_unicode=True), encoding="utf-8")
    assert _run(project_root, env, "--config", str(config), "init", str(video)).returncode == 0
    ws = tmp_path / "workspace" / "lesson"
    (ws / "lecture").mkdir(parents=True, exist_ok=True); (ws / "evidence").mkdir(parents=True, exist_ok=True)
    lecture = {
        "schema_version": "1.0", "stage": "completion_draft", "metadata": {}, "overview": {},
        "sections": [{"id": "sec_01", "title": "方法", "blocks": []}],
        "problems": [], "supplements": [], "figures": [], "summary": [], "review": {"issues": []},
    }
    (ws / "lecture" / "lecture.json").write_text(json.dumps(lecture, ensure_ascii=False), encoding="utf-8")
    (ws / "evidence" / "timeline.json").write_text('{"timeline": []}', encoding="utf-8")
    tasks = ws / "tasks" / "review"; responses = ws / "responses" / "review"; responses.mkdir(parents=True, exist_ok=True)

    assert _run(project_root, env, "--config", str(config), "review", "prepare", str(video)).returncode == 0
    ped_req = json.loads((tasks / "pedagogical.request.json").read_text(encoding="utf-8"))
    (responses / "pedagogical.json").write_text(json.dumps({
        "request_id": ped_req["request_id"],
        "issues": [{"target_id": "sec_01", "severity": "info", "label": "clarity", "message": "增加方法小结。", "source_value": None, "review_value": None}],
    }, ensure_ascii=False), encoding="utf-8")
    assert _run(project_root, env, "--config", str(config), "review", "prepare", str(video)).returncode == 0
    req = json.loads((tasks / "ped_repair_r1_sec_01.request.json").read_text(encoding="utf-8"))
    assert req["required_model"] == "terra-xhigh"
    (responses / "ped_repair_r1_sec_01.json").write_text(json.dumps({
        "request_id": req["request_id"],
        "repairs": [{"issue_id": "pg_001", "target_id": "sec_01", "status": "resolved", "action": "append_summary", "content": "方法小结：先识别条件，再组织推导。"}],
    }, ensure_ascii=False), encoding="utf-8")
    assert _run(project_root, env, "--config", str(config), "review", "prepare", str(video)).returncode == 0
    manifest = json.loads((tasks / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "ready"
    assert not (tasks / "ped_repair_r2_sec_01.request.json").exists()
    assert _run(project_root, env, "--config", str(config), "review", "apply", str(video)).returncode == 0
    reviewed = json.loads((ws / "lecture" / "lecture.json").read_text(encoding="utf-8"))
    assert reviewed["summary"][0]["content"] == "方法小结：先识别条件，再组织推导。"
    assert reviewed["review"]["pedagogical_repair"]["resolved"] == 1
    assert reviewed["review"]["pedagogical_repair"]["unresolved"] == 0
