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


def test_completion_cli_pipeline(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake")

    workspace_root = tmp_path / "workspace"
    response_file = tmp_path / "completion_response.json"
    response_file.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "target_id": "P01",
                        "reason": "incomplete_explanation",
                        "why_needed": "老师直接给出结论，缺少中间关系。",
                        "content": "由对应角相等可先得到两个三角形相似。",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
project:
  workspace_root: "{workspace_root.as_posix()}"
  project_root: "{project_root.as_posix()}"

completion:
  prompts_file: "package:prompts.yaml"
  max_items_per_call: 12
  reject_unreferenced_targets: true
  llm:
    provider: "file"
    response_files:
      - "{response_file.as_posix()}"
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

    lecture = {
        "schema_version": "1.0",
        "stage": "reconstruction_draft",
        "metadata": {},
        "overview": {},
        "sections": [
            {
                "id": "sec_01",
                "title": "相似三角形",
                "blocks": [],
                "evidence_ids": ["ev_0001"],
            }
        ],
        "problems": [
            {
                "id": "P01",
                "title": "例题1",
                "statement": {
                    "content": "题目",
                    "origin": "video",
                    "evidence_ids": ["ev_0001"],
                    "status": "confirmed",
                },
                "teacher_solution": {
                    "content": "直接得到结论",
                    "origin": "video",
                    "evidence_ids": ["ev_0002"],
                    "status": "confirmed",
                },
                "teacher_answer": None,
            }
        ],
        "supplements": [],
        "figures": [],
        "summary": [],
        "review": {"issues": []},
    }

    original_problem = json.loads(
        json.dumps(lecture["problems"][0], ensure_ascii=False)
    )

    (ws / "lecture" / "lecture.json").write_text(
        json.dumps(lecture, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = _run(
        ["--config", str(config), "complete", "api", str(video)],
        project_root,
        env,
    )
    assert result.returncode == 0, result.stderr

    completed = json.loads(
        (ws / "lecture" / "lecture.json").read_text(encoding="utf-8")
    )

    assert completed["stage"] == "completion_draft"
    assert completed["problems"][0] == original_problem
    assert len(completed["supplements"]) == 1
    assert completed["supplements"][0]["origin"] == "supplement"
    assert completed["supplements"][0]["target_id"] == "P01"

    completion_file = ws / "lecture" / "completion" / "completion.json"
    report = ws / "reports" / "completion_report.json"

    assert completion_file.exists()
    assert report.exists()
