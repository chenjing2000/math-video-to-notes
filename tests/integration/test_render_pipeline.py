import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _run(args, cwd, env):
    return subprocess.run(
        [sys.executable, "-m", "video_to_notes", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(
    shutil.which("xelatex") is None,
    reason="xelatex is not installed",
)
def test_render_cli_pipeline_with_real_xelatex(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake")
    workspace_root = tmp_path / "workspace"

    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
project:
  workspace_root: "{workspace_root.as_posix()}"
  project_root: "{project_root.as_posix()}"

render:
  template: "package:lecture.tex.j2"
  engine: "xelatex"
  runs: 2
  timeout_seconds: 120
  interaction: "nonstopmode"
  halt_on_error: true
  fail_on_missing_image: true
  fail_on_missing_character: true
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
        "stage": "review_draft",
        "metadata": {
            "title": "相似三角形测试讲义",
            "source": "integration test",
            "duration": "00:10:00",
        },
        "overview": {
            "topic": "相似三角形",
            "main_line": "从比例关系到例题",
            "learning_objectives": [
                "理解相似三角形的基本比例关系",
                "会处理 $a_b=c$ 形式的数学表达"
            ],
            "core_methods": ["对应边成比例"],
        },
        "sections": [
            {
                "id": "sec_01",
                "title": "基本知识",
                "blocks": [
                    {
                        "id": "blk_001",
                        "type": "knowledge",
                        "content": "若两个三角形相似，则对应边成比例，例如 $a/b=c/d$。",
                        "origin": "video",
                        "status": "confirmed",
                        "evidence_ids": ["ev_0001"],
                    },
                    {
                        "id": "blk_002",
                        "type": "observation",
                        "content": "先找对应角，再建立对应边。",
                        "origin": "reconstructed",
                        "status": "confirmed",
                        "evidence_ids": ["ev_0001"],
                    },
                ],
            }
        ],
        "problems": [
            {
                "id": "P01",
                "section_id": "sec_01",
                "title": "例题 1",
                "statement": {
                    "content": "已知 $AB/AC=2/3$，求对应边比例。",
                    "origin": "video",
                    "evidence_ids": ["ev_0002"],
                    "status": "confirmed",
                },
                "analysis": {
                    "content": "直接利用对应边成比例。",
                    "origin": "reconstructed",
                    "evidence_ids": ["ev_0002"],
                    "status": "confirmed",
                },
                "teacher_solution": {
                    "content": "由相似关系可得 $AB:AC=2:3$。",
                    "origin": "video",
                    "evidence_ids": ["ev_0003"],
                    "status": "confirmed",
                },
                "teacher_answer": {
                    "content": "$2:3$",
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
                "why_needed": "说明比例关系的来源。",
                "content": "这里使用的是相似三角形对应边成比例。",
                "origin": "supplement",
                "status": "confirmed",
            }
        ],
        "figures": [],
        "summary": [
            "先识别对应关系，再列比例式。",
            "所有比例都必须保持对应顺序一致。"
        ],
        "review": {
            "issues": []
        },
    }

    (ws / "lecture" / "lecture.json").write_text(
        json.dumps(lecture, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = _run(
        ["--config", str(config), "render", str(video)],
        project_root,
        env,
    )
    assert result.returncode == 0, result.stderr

    tex = ws / "latex" / "lecture.tex"
    pdf = ws / "output" / "lecture.pdf"
    report = ws / "reports" / "render_report.json"

    assert tex.exists()
    assert pdf.exists()
    assert pdf.stat().st_size > 0
    assert report.exists()

    report_data = json.loads(report.read_text(encoding="utf-8"))
    assert report_data["latex_metrics"]["latex_errors"] == 0
    assert report_data["latex_metrics"]["missing_characters"] == 0

    rendered_lecture = json.loads(
        (ws / "lecture" / "lecture.json").read_text(encoding="utf-8")
    )
    assert rendered_lecture["stage"] == "rendered"
