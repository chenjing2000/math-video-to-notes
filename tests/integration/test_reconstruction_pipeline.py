from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


@pytest.mark.integration
def test_reconstruction_cli_pipeline(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake-video")

    chunk_response = tmp_path / "chunk.json"
    merge_response = tmp_path / "merge.json"

    chunk_response.write_text(
        json.dumps(
            {
                "topics": [
                    {
                        "title": "定义",
                        "content": "定义内容",
                        "origin": "video",
                        "evidence_ids": ["ev_0000"],
                        "status": "confirmed",
                    }
                ],
                "problems": [],
                "section_hints": [
                    {"title": "第一节", "evidence_ids": ["ev_0000"]}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    merge_response.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "stage": "reconstruction_draft",
                "metadata": {},
                "overview": {
                    "topic": "测试课",
                    "main_line": "定义",
                    "core_methods": [],
                    "learning_objectives": [],
                },
                "sections": [
                    {
                        "id": "sec_01",
                        "title": "第一节",
                        "type": "concept",
                        "source_ranges": [[0.0, 10.0]],
                        "evidence_ids": ["ev_0000"],
                        "blocks": [
                            {
                                "id": "blk_001",
                                "type": "definition",
                                "content": "定义内容",
                                "origin": "video",
                                "evidence_ids": ["ev_0000"],
                                "status": "confirmed",
                            }
                        ],
                    }
                ],
                "problems": [],
                "supplements": [],
                "figures": [],
                "summary": [],
                "review": {"issues": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    workspace_root = tmp_path / "workspace"
    config = {
        "project": {
            "workspace_root": str(workspace_root),
            "copy_source_video": False,
            "project_root": str(project_root),
        },
        "reconstruction": {
            "prompts_file": "package:prompts.yaml",
            "max_evidence_chars_per_chunk": 28000,
            "llm": {
                "provider": "file",
                "response_files": [
                    str(chunk_response),
                    str(merge_response),
                ],
            },
        },
    }
    config_path = tmp_path / "test_config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    init = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_to_notes",
            "--config",
            str(config_path),
            "init",
            str(video),
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert init.returncode == 0, init.stderr

    workspace = workspace_root / "lesson"
    (workspace / "evidence").mkdir(parents=True, exist_ok=True)
    (workspace / "evidence" / "timeline.json").write_text(
        json.dumps(
            {
                "timeline": [
                    {
                        "id": "ev_0000",
                        "start": 0.0,
                        "end": 10.0,
                        "visual_type": "stable_slide",
                        "frame_ids": ["evf_000000"],
                        "transcript_text": "定义内容",
                        "confidence": 0.9,
                        "status": "confirmed",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_to_notes",
            "--config",
            str(config_path),
            "reconstruct",
            "api",
            str(video),
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (workspace / "lecture" / "lecture.json").exists()
    assert (workspace / "reports" / "reconstruction_report.json").exists()

    lecture = json.loads(
        (workspace / "lecture" / "lecture.json").read_text(encoding="utf-8")
    )
    assert lecture["stage"] == "reconstruction_draft"
    assert lecture["sections"][0]["evidence_ids"] == ["ev_0000"]
    assert lecture["supplements"] == []
