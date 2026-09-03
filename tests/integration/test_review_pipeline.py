import copy
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


def test_review_cli_pipeline(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake")
    workspace_root = tmp_path / "workspace"

    factual_response = tmp_path / "factual.json"
    factual_response.write_text(
        json.dumps({
            "issues": []
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    math_response = tmp_path / "math.json"
    math_response.write_text(
        json.dumps({
            "reviewed_solutions": [{
                "target_id": "P01.teacher_solution",
                "status": "revised",
                "content": "由正确的角度关系推导，得到 $46^\\circ$。",
            }],
            "reviewed_answers": [{
                "target_id": "P01.teacher_answer",
                "status": "revised",
                "content": "$46^\\circ$",
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    pedagogical_response = tmp_path / "pedagogical.json"
    pedagogical_response.write_text(
        json.dumps({
            "issues": [
                {
                    "target_id": "sec_01",
                    "severity": "info",
                    "label": "clarity",
                    "message": "章节结尾可增加一句方法归纳。",
                    "source_value": None,
                    "review_value": None
                }
            ]
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
project:
  workspace_root: "{workspace_root.as_posix()}"
  project_root: "{project_root.as_posix()}"

review:
  prompts_file: "package:prompts.yaml"
  reject_unreferenced_targets: true

  factual:
    enabled: true
    trigger_statuses: [probable, uncertain, conflict]
    always_review_problem_fields: [statement, teacher_solution, teacher_answer]
    llm:
      provider: "file"
      response_files:
        - "{factual_response.as_posix()}"

  math:
    enabled: true
    review_all_problems: true
    llm:
      provider: "file"
      response_files:
        - "{math_response.as_posix()}"

  pedagogical:
    enabled: true
    whole_lecture: true
    llm:
      provider: "file"
      response_files:
        - "{pedagogical_response.as_posix()}"
""".strip(),
        encoding="utf-8",
    )

    init = _run(
        ["--config", str(config), "init", str(video)],
        project_root,
        env,
    )
    assert init.returncode == 0, init.stderr

    ws = workspace_root / "lesson"
    (ws / "lecture").mkdir(parents=True, exist_ok=True)
    (ws / "evidence").mkdir(parents=True, exist_ok=True)

    lecture = {
        "schema_version": "1.0",
        "stage": "completion_draft",
        "metadata": {},
        "overview": {},
        "sections": [
            {
                "id": "sec_01",
                "title": "角度关系",
                "blocks": [],
                "evidence_ids": ["ev_0001"],
            }
        ],
        "problems": [
            {
                "id": "P01",
                "title": "例题1",
                "statement": {
                    "content": "已知条件，求角度。",
                    "origin": "video",
                    "evidence_ids": ["ev_0001"],
                    "status": "confirmed",
                },
                "teacher_solution": {
                    "content": "由角度关系推导。",
                    "origin": "video",
                    "evidence_ids": ["ev_0002"],
                    "status": "confirmed",
                },
                "teacher_answer": {
                    "content": "48°",
                    "origin": "video",
                    "evidence_ids": ["ev_0003"],
                    "status": "confirmed",
                },
            }
        ],
        "supplements": [
            {
                "id": "sup_001",
                "target_id": "P01",
                "reason": "pedagogical_bridge",
                "why_needed": "补足一步逻辑。",
                "content": "先建立角度对应关系。",
                "origin": "supplement",
                "status": "confirmed",
            }
        ],
        "figures": [],
        "summary": [],
        "review": {"issues": []},
    }
    original_body = copy.deepcopy({
        "sections": lecture["sections"],
        "problems": lecture["problems"],
        "supplements": lecture["supplements"],
    })

    timeline = {
        "schema_version": "1.0",
        "timeline": [
            {
                "id": "ev_0001",
                "start": 0.0,
                "end": 10.0,
                "visual_type": "stable_slide",
                "frame_ids": ["evf_000001"],
                "transcript_text": "已知条件，求角度。",
                "confidence": 0.95,
                "status": "confirmed",
            },
            {
                "id": "ev_0002",
                "start": 10.0,
                "end": 20.0,
                "visual_type": "progressive_board",
                "frame_ids": ["evf_000002"],
                "transcript_text": "由角度关系推导。",
                "confidence": 0.95,
                "status": "confirmed",
            },
            {
                "id": "ev_0003",
                "start": 20.0,
                "end": 25.0,
                "visual_type": "progressive_board",
                "frame_ids": ["evf_000003"],
                "transcript_text": "答案四十八度。",
                "confidence": 0.95,
                "status": "confirmed",
            },
        ],
        "orphan_transcripts": [],
    }

    (ws / "lecture" / "lecture.json").write_text(
        json.dumps(lecture, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ws / "evidence" / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = _run(
        ["--config", str(config), "review", "api", str(video)],
        project_root,
        env,
    )
    assert result.returncode == 0, result.stderr

    reviewed = json.loads(
        (ws / "lecture" / "lecture.json").read_text(encoding="utf-8")
    )

    assert reviewed["stage"] == "review_draft"
    assert reviewed["sections"] == original_body["sections"]
    assert reviewed["problems"][0]["teacher_solution"]["content"] == "由角度关系推导。"
    assert reviewed["problems"][0]["teacher_answer"]["content"] == "48°"
    assert reviewed["problems"][0]["publication_solution"]["review_status"] == "revised"
    assert "$46^\\circ$" in reviewed["problems"][0]["publication_solution"]["content"]
    assert reviewed["problems"][0]["publication_answer"]["content"] == "$46^\\circ$"
    assert reviewed["supplements"] == original_body["supplements"]

    issues = reviewed["review"]["issues"]
    assert len(issues) == 1
    assert issues[0]["review_type"] == "pedagogical"

    assert (ws / "review" / "issues.json").exists()
    assert (ws / "reports" / "review_report.json").exists()


def test_review_api_escalates_medium_unresolved_to_high(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake")
    workspace_root = tmp_path / "workspace"

    factual_response = tmp_path / "factual.json"
    factual_response.write_text(json.dumps({"issues": []}), encoding="utf-8")
    medium_response = tmp_path / "medium.json"
    medium_response.write_text(json.dumps({
        "reviewed_solutions": [{"target_id": "P01.teacher_solution", "status": "unresolved"}],
        "reviewed_answers": [{"target_id": "P01.teacher_answer", "status": "verified"}],
    }, ensure_ascii=False), encoding="utf-8")
    high_response = tmp_path / "high.json"
    high_response.write_text(json.dumps({
        "reviewed_solutions": [{
            "target_id": "P01.teacher_solution", "status": "revised", "content": "Sol High 修正后的完整解法"
        }],
        "reviewed_answers": [],
    }, ensure_ascii=False), encoding="utf-8")
    pedagogical_response = tmp_path / "pedagogical.json"
    pedagogical_response.write_text(json.dumps({"issues": []}), encoding="utf-8")

    config = tmp_path / "config.yaml"
    config.write_text(f'''project:
  workspace_root: "{workspace_root.as_posix()}"
  project_root: "{project_root.as_posix()}"
review:
  factual:
    llm:
      provider: file
      response_files: ["{factual_response.as_posix()}"]
  math:
    llm:
      provider: file
      response_files: ["{medium_response.as_posix()}"]
    high_llm:
      provider: file
      response_files: ["{high_response.as_posix()}"]
  pedagogical:
    llm:
      provider: file
      response_files: ["{pedagogical_response.as_posix()}"]
''', encoding="utf-8")

    assert _run(["--config", str(config), "init", str(video)], project_root, env).returncode == 0
    ws = workspace_root / "lesson"
    (ws / "lecture").mkdir(parents=True, exist_ok=True)
    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    lecture = {
        "schema_version": "1.0", "stage": "completion_draft", "metadata": {}, "overview": {}, "sections": [],
        "problems": [{
            "id": "P01", "statement": {"content": "求证 A=B", "evidence_ids": ["ev_1"], "status": "confirmed"},
            "teacher_solution": {"content": "原解", "evidence_ids": ["ev_2"], "status": "confirmed"},
            "teacher_answer": {"content": "A=B", "evidence_ids": ["ev_3"], "status": "confirmed"},
        }],
        "supplements": [], "figures": [], "summary": [], "review": {"issues": []},
    }
    timeline = {"timeline": [
        {"id": "ev_1", "start": 0, "end": 1, "frame_ids": [], "frames": [], "transcript_text": "题目", "status": "confirmed"},
        {"id": "ev_2", "start": 1, "end": 2, "frame_ids": [], "frames": [], "transcript_text": "原解", "status": "confirmed"},
        {"id": "ev_3", "start": 2, "end": 3, "frame_ids": [], "frames": [], "transcript_text": "答案", "status": "confirmed"},
    ]}
    (ws / "lecture/lecture.json").write_text(json.dumps(lecture, ensure_ascii=False), encoding="utf-8")
    (ws / "evidence/timeline.json").write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")

    result = _run(["--config", str(config), "review", "api", str(video)], project_root, env)
    assert result.returncode == 0, result.stderr
    reviewed = json.loads((ws / "lecture/lecture.json").read_text(encoding="utf-8"))
    assert reviewed["problems"][0]["publication_solution"]["content"] == "Sol High 修正后的完整解法"
    assert reviewed["problems"][0]["publication_solution"]["review_model"] == "sol-high"
    report = json.loads((ws / "reports/review_report.json").read_text(encoding="utf-8"))
    assert report["reviewers"]["math"]["high_escalations"] == 1
    assert report["math_review"]["unresolved"] == 0


def test_review_api_pedagogical_repair_with_explicit_file_provider(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake")
    workspace_root = tmp_path / "workspace"

    pedagogical_response = tmp_path / "pedagogical.json"
    pedagogical_response.write_text(json.dumps({
        "issues": [{
            "target_id": "sec_01",
            "severity": "info",
            "label": "clarity",
            "message": "增加方法归纳。",
            "source_value": None,
            "review_value": None,
        }]
    }, ensure_ascii=False), encoding="utf-8")
    repair_response = tmp_path / "repair.json"
    repair_response.write_text(json.dumps({
        "repairs": [{
            "issue_id": "pg_001",
            "target_id": "sec_01",
            "status": "resolved",
            "action": "append_summary",
            "content": "方法归纳：先识别条件，再组织推导。",
        }]
    }, ensure_ascii=False), encoding="utf-8")

    config = tmp_path / "config.yaml"
    config.write_text(f'''project:\n  workspace_root: "{workspace_root.as_posix()}"\n  project_root: "{project_root.as_posix()}"\n\nreview:\n  factual:\n    enabled: false\n  math:\n    enabled: false\n  pedagogical:\n    enabled: true\n    whole_lecture: true\n    llm:\n      provider: "file"\n      response_files:\n        - "{pedagogical_response.as_posix()}"\n    repair:\n      enabled: true\n      llm:\n        provider: "file"\n        response_files:\n          - "{repair_response.as_posix()}"\n''', encoding="utf-8")

    init = _run(["--config", str(config), "init", str(video)], project_root, env)
    assert init.returncode == 0, init.stderr
    ws = workspace_root / "lesson"
    (ws / "lecture").mkdir(parents=True, exist_ok=True)
    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    lecture = {
        "schema_version": "1.0", "stage": "completion_draft", "metadata": {}, "overview": {},
        "sections": [{"id": "sec_01", "title": "方法", "blocks": []}],
        "problems": [], "supplements": [], "figures": [], "summary": [], "review": {"issues": []},
    }
    (ws / "lecture" / "lecture.json").write_text(json.dumps(lecture, ensure_ascii=False), encoding="utf-8")
    (ws / "evidence" / "timeline.json").write_text('{"timeline": []}', encoding="utf-8")

    result = _run(["--config", str(config), "review", "api", str(video)], project_root, env)
    assert result.returncode == 0, result.stderr
    reviewed = json.loads((ws / "lecture" / "lecture.json").read_text(encoding="utf-8"))
    assert reviewed["summary"][0]["content"] == "方法归纳：先识别条件，再组织推导。"
    assert reviewed["review"]["pedagogical_repair"]["resolved"] == 1
    assert reviewed["review"]["pedagogical_repair"]["unresolved"] == 0
