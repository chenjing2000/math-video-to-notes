import json
import logging
from pathlib import Path

from video_to_notes.reconstruction.stage import run_reconstruction_stage
from video_to_notes.stages import StageContext


def test_reconstruction_stage_with_file_provider(tmp_path):
    project_root = tmp_path / "project"
    workspace = tmp_path / "workspace"
    (project_root / "config").mkdir(parents=True)
    (workspace / "evidence").mkdir(parents=True)
    (workspace / "source").mkdir(parents=True)
    (workspace / "reports").mkdir(parents=True)

    prompts = {
        "reconstruction": {
            "chunk": {
                "version": "1",
                "system": "chunk system",
                "user": "{{EVIDENCE_JSON}}",
            },
            "merge": {
                "version": "1",
                "system": "merge system",
                "user": "{{CHUNKS_JSON}}",
            },
        }
    }
    import yaml
    (project_root / "config" / "prompts.yaml").write_text(
        yaml.safe_dump(prompts, allow_unicode=True), encoding="utf-8"
    )

    (workspace / "project.json").write_text(
        json.dumps({
            "project_name": "lesson",
            "source": {"original_path": "lesson.mp4"},
        }),
        encoding="utf-8",
    )
    (workspace / "source" / "video_info.json").write_text(
        json.dumps({"duration": 20.0}), encoding="utf-8"
    )
    (workspace / "evidence" / "timeline.json").write_text(
        json.dumps({
            "timeline": [
                {
                    "id": "ev_0000",
                    "start": 0.0,
                    "end": 10.0,
                    "visual_type": "stable_slide",
                    "frame_ids": ["evf_000001"],
                    "transcript_text": "这是定义。",
                    "confidence": 0.9,
                    "status": "confirmed",
                }
            ]
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    chunk_response = project_root / "chunk.json"
    merge_response = project_root / "merge.json"
    chunk_response.write_text(json.dumps({
        "topics": [
            {
                "title": "定义",
                "content": "这是定义。",
                "origin": "video",
                "evidence_ids": ["ev_0000"],
                "status": "confirmed",
            }
        ],
        "problems": [],
        "section_hints": [
            {"title": "基础概念", "evidence_ids": ["ev_0000"]}
        ],
    }, ensure_ascii=False), encoding="utf-8")

    merge_response.write_text(json.dumps({
        "schema_version": "1.0",
        "stage": "reconstruction_draft",
        "metadata": {},
        "overview": {
            "topic": "基础概念",
            "main_line": "定义",
            "core_methods": [],
            "learning_objectives": [],
        },
        "sections": [
            {
                "id": "sec_01",
                "title": "基础概念",
                "type": "concept",
                "source_ranges": [[0.0, 10.0]],
                "evidence_ids": ["ev_0000"],
                "blocks": [
                    {
                        "id": "blk_001",
                        "type": "definition",
                        "content": "这是定义。",
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
    }, ensure_ascii=False), encoding="utf-8")

    config = {
        "project": {"project_root": str(project_root)},
        "reconstruction": {
            "prompts_file": "package:prompts.yaml",
            "max_evidence_chars_per_chunk": 10000,
            "llm": {
                "provider": "file",
                "response_files": [
                    str(chunk_response),
                    str(merge_response),
                ],
            },
        },
    }

    ctx = StageContext(
        stage="reconstruction",
        workspace_root=workspace,
        config=config,
        logger=logging.getLogger("test_reconstruction"),
    )
    run_reconstruction_stage(ctx)

    lecture_path = workspace / "lecture" / "lecture.json"
    assert lecture_path.exists()
    lecture = json.loads(lecture_path.read_text(encoding="utf-8"))
    assert lecture["stage"] == "reconstruction_draft"
    assert lecture["sections"][0]["evidence_ids"] == ["ev_0000"]
    assert lecture["supplements"] == []
