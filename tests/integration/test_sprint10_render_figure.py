from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


def _run(args, cwd, env):
    return subprocess.run(
        [sys.executable, "-m", "video_to_notes", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex is not installed")
def test_render_binds_and_compiles_problem_figure(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake")
    workspace_root = tmp_path / "workspace"
    config = tmp_path / "config.yaml"
    config.write_text(f'''project:\n  workspace_root: "{workspace_root.as_posix()}"\n  project_root: "{project_root.as_posix()}"\nrender:\n  template: "package:lecture.tex.j2"\n  engine: "xelatex"\n  runs: 2\n  fail_on_missing_image: true\n  fail_on_missing_character: true\n''', encoding="utf-8")

    assert _run(["--config", str(config), "init", str(video)], project_root, env).returncode == 0
    ws = workspace_root / "lesson"
    frame = ws / "visual" / "evidence_frames" / "evf_000001.jpg"
    frame.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.line((80, 290, 320, 60), fill="black", width=4)
    draw.line((320, 60, 560, 290), fill="black", width=4)
    draw.line((80, 290, 560, 290), fill="black", width=4)
    image.save(frame)

    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    (ws / "evidence" / "timeline.json").write_text(json.dumps({"timeline": [{
        "id": "ev_0001",
        "start": 0.0,
        "end": 10.0,
        "visual_type": "stable_slide",
        "frame_ids": ["evf_000001"],
        "frames": [{"id": "evf_000001", "time": 2.0, "path": str(frame)}],
        "status": "confirmed",
    }]}, ensure_ascii=False), encoding="utf-8")

    (ws / "lecture").mkdir(parents=True, exist_ok=True)
    lecture = {
        "schema_version": "1.0",
        "stage": "review_draft",
        "metadata": {"title": "图形测试"},
        "overview": {},
        "sections": [],
        "problems": [{
            "id": "P01",
            "title": "几何题",
            "statement": {
                "content": "如图，在三角形 ABC 中，D 为 BC 的中点。",
                "origin": "video",
                "evidence_ids": ["ev_0001"],
                "status": "confirmed",
            },
            "teacher_solution": {"content": "老师解法。", "origin": "video", "evidence_ids": ["ev_0001"], "status": "confirmed"},
            "teacher_answer": None,
        }],
        "supplements": [],
        "figures": [],
        "summary": [],
        "review": {"issues": []},
    }
    (ws / "lecture" / "lecture.json").write_text(json.dumps(lecture, ensure_ascii=False), encoding="utf-8")

    result = _run(["--config", str(config), "render", str(video)], project_root, env)
    assert result.returncode == 0, result.stderr
    report = json.loads((ws / "reports" / "render_report.json").read_text(encoding="utf-8"))
    assert report["images_copied"] == 1
    assert report["figure_binding"]["figures_bound"] == 1
    assert report["latex_metrics"]["missing_characters"] == 0
    assert (ws / "output" / "lecture.pdf").exists()
