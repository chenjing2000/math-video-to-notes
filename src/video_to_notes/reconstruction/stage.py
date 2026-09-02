from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..config import resolve_resource_path
from ..errors import StageError
from ..stages import StageContext
from ..util import atomic_write_json, read_json
from .chunking import chunk_evidence
from .prompts import load_prompts, render
from .provider import build_provider
from .validation import validate_chunk, validate_lecture_draft
from .figures import bind_problem_figures


def _resolve_project_root(ctx: StageContext) -> Path:
    configured = ctx.config.get("project", {}).get("project_root")
    if configured:
        return Path(str(configured)).expanduser().resolve()
    return Path.cwd().resolve()


def _load_timeline(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise StageError(f"缺少 Evidence Timeline: {path}。请先运行 evidence stage。")
    data = read_json(path)
    timeline = data.get("timeline") if isinstance(data, dict) else None
    if not isinstance(timeline, list) or not timeline:
        raise StageError("Evidence Timeline 为空。")
    return timeline


def _compact_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "start": item.get("start"),
        "end": item.get("end"),
        "visual_type": item.get("visual_type"),
        "frame_ids": item.get("frame_ids", []),
        "frames": [
            {
                "id": frame.get("id"),
                "time": frame.get("time"),
                "path": frame.get("path"),
            }
            for frame in item.get("frames", [])
            if isinstance(frame, dict)
        ],
        "transcript_text": item.get("transcript_text", ""),
        "confidence": item.get("confidence"),
        "status": item.get("status"),
    }


def _enrich_metadata(lecture: dict[str, Any], ctx: StageContext) -> None:
    project = read_json(ctx.workspace_root / "project.json")
    video_info_path = ctx.workspace_root / "source" / "video_info.json"
    video_info = read_json(video_info_path) if video_info_path.exists() else {}

    metadata = lecture.setdefault("metadata", {})
    metadata.setdefault("project_name", project.get("project_name"))
    metadata.setdefault("source_path", project.get("source", {}).get("original_path"))
    if isinstance(video_info, dict):
        metadata.setdefault("duration", video_info.get("duration"))


def run_reconstruction_stage(ctx: StageContext) -> None:
    logger: logging.Logger = ctx.logger
    cfg = ctx.config["reconstruction"]
    project_root = _resolve_project_root(ctx)

    timeline_path = ctx.workspace_root / "evidence" / "timeline.json"
    timeline = _load_timeline(timeline_path)
    valid_ids = {str(item["id"]) for item in timeline if "id" in item}

    prompt_path = resolve_resource_path(cfg.get("prompts_file", "package:prompts.yaml"), default_name="prompts.yaml")
    prompts = load_prompts(prompt_path.resolve())
    recon_prompts = prompts.get("reconstruction", {})
    chunk_prompt = recon_prompts.get("chunk", {})
    merge_prompt = recon_prompts.get("merge", {})
    if not isinstance(chunk_prompt, dict) or not isinstance(merge_prompt, dict):
        raise StageError("prompts.yaml 缺少 reconstruction.chunk/merge。")

    provider = build_provider(cfg["llm"], project_root=project_root)

    compact = [_compact_evidence(item) for item in timeline]
    chunks = chunk_evidence(
        compact,
        max_chars=int(cfg.get("max_evidence_chars_per_chunk", 28000)),
    )
    logger.info(
        "[reconstruction] evidence=%d chunks=%d",
        len(compact),
        len(chunks),
    )

    recon_dir = ctx.workspace_root / "lecture" / "reconstruction"
    chunks_dir = recon_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunk_results: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        logger.info(
            "[reconstruction] chunk %d/%d evidence=%d",
            index + 1,
            len(chunks),
            len(chunk),
        )
        user = render(
            str(chunk_prompt["user"]),
            "EVIDENCE_JSON",
            json.dumps(chunk, ensure_ascii=False, indent=2),
        )
        result = provider.generate_json(
            system=str(chunk_prompt["system"]),
            user=user,
        )
        validate_chunk(result, valid_ids)
        atomic_write_json(chunks_dir / f"chunk_{index:04d}.json", result)
        chunk_results.append(result)

    merge_user = render(
        str(merge_prompt["user"]),
        "CHUNKS_JSON",
        json.dumps(chunk_results, ensure_ascii=False, indent=2),
    )
    lecture = provider.generate_json(
        system=str(merge_prompt["system"]),
        user=merge_user,
    )
    validate_lecture_draft(lecture, valid_ids)
    _enrich_metadata(lecture, ctx)
    figure_report = bind_problem_figures(
        lecture,
        timeline,
        workspace_root=ctx.workspace_root,
        infer_from_statement=bool(cfg.get("infer_problem_figures", True)),
        max_figures_per_problem=int(cfg.get("max_figures_per_problem", 2)),
    )

    lecture_dir = ctx.workspace_root / "lecture"
    lecture_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(lecture_dir / "lecture.json", lecture)

    problem_count = len(lecture.get("problems", []))
    section_count = len(lecture.get("sections", []))
    report = {
        "schema_version": "1.0",
        "stage": "reconstruction",
        "evidence_segments": len(timeline),
        "chunks": len(chunks),
        "sections": section_count,
        "problems": problem_count,
        "figures": figure_report,
        "prompt_versions": {
            "chunk": str(chunk_prompt.get("version", "unknown")),
            "merge": str(merge_prompt.get("version", "unknown")),
        },
        "llm": {
            "provider": cfg.get("llm", {}).get("provider"),
            "model": cfg.get("llm", {}).get("model"),
        },
        "output": str(lecture_dir / "lecture.json"),
    }
    atomic_write_json(
        ctx.workspace_root / "reports" / "reconstruction_report.json",
        report,
    )
    logger.info(
        "[reconstruction] sections=%d problems=%d",
        section_count,
        problem_count,
    )
