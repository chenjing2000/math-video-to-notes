from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..config import resolve_resource_path
from ..errors import StageError
from ..stages import StageContext
from ..util import atomic_write_json, read_json
from ..reconstruction.prompts import load_prompts, render
from ..reconstruction.figures import bind_problem_figures
from ..reconstruction.provider import build_provider
from .chunking import make_completion_chunks
from .assessment import infer_requires_solution, infer_solution_completeness
from .validation import collect_valid_targets, validate_completion_items


def _resolve_project_root(ctx: StageContext) -> Path:
    configured = ctx.config.get("project", {}).get("project_root")
    if configured:
        return Path(str(configured)).expanduser().resolve()
    return Path.cwd().resolve()


def _load_lecture(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise StageError(
            f"缺少 lecture.json: {path}。请先运行 reconstruct stage。"
        )
    lecture = read_json(path)
    if not isinstance(lecture, dict):
        raise StageError("lecture.json 根节点必须为 object。")
    return lecture


def _compact_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": chunk.get("items", []),
    }


def run_completion_stage(ctx: StageContext) -> None:
    logger: logging.Logger = ctx.logger
    cfg = ctx.config["completion"]
    project_root = _resolve_project_root(ctx)

    lecture_path = ctx.workspace_root / "lecture" / "lecture.json"
    lecture = _load_lecture(lecture_path)

    stage = str(lecture.get("stage", ""))
    if stage not in {"reconstruction_draft", "completion_draft", "review_draft", "rendered", "audited"}:
        raise StageError(
            "completion stage 可从 reconstruction_draft/completion_draft/review_draft/rendered/audited 重新开始。"
        )

    timeline_path = ctx.workspace_root / "evidence" / "timeline.json"
    if timeline_path.exists():
        timeline_data = read_json(timeline_path)
        timeline = timeline_data.get("timeline", []) if isinstance(timeline_data, dict) else []
        if isinstance(timeline, list):
            bind_problem_figures(
                lecture,
                timeline,
                workspace_root=ctx.workspace_root,
                infer_from_statement=bool(ctx.config.get("reconstruction", {}).get("infer_problem_figures", True)),
                max_figures_per_problem=int(ctx.config.get("reconstruction", {}).get("max_figures_per_problem", 2)),
            )
            atomic_write_json(lecture_path, lecture)

    prompt_path = resolve_resource_path(cfg.get("prompts_file", "package:prompts.yaml"), default_name="prompts.yaml")

    prompts = load_prompts(prompt_path.resolve())
    completion_prompts = prompts.get("completion", {})
    analyze_prompt = completion_prompts.get("analyze", {})
    merge_prompt = completion_prompts.get("merge", {})
    if not isinstance(analyze_prompt, dict) or not isinstance(merge_prompt, dict):
        raise StageError("prompts.yaml 缺少 completion.analyze/merge。")

    provider = build_provider(
        cfg["llm"],
        project_root=project_root,
    )

    valid_targets = collect_valid_targets(lecture)
    chunks = make_completion_chunks(
        lecture,
        max_items_per_call=int(cfg.get("max_items_per_call", 12)),
    )

    logger.info(
        "[completion] targets=%d chunks=%d",
        len(valid_targets),
        len(chunks),
    )

    completion_dir = ctx.workspace_root / "lecture" / "completion"
    candidates_dir = completion_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    candidate_batches: list[dict[str, Any]] = []

    for index, chunk in enumerate(chunks):
        logger.info(
            "[completion] chunk %d/%d items=%d",
            index + 1,
            len(chunks),
            len(chunk.get("items", [])),
        )

        user = render(
            str(analyze_prompt["user"]),
            "LECTURE_JSON",
            json.dumps(
                _compact_chunk(chunk),
                ensure_ascii=False,
                indent=2,
            ),
        )
        result = provider.generate_json(
            system=str(analyze_prompt["system"]),
            user=user,
        )

        items = result.get("items")
        if not isinstance(items, list):
            raise StageError("completion analyze 返回 items 非 list。")

        # Validate each batch immediately so invalid model output cannot propagate.
        validate_completion_items(
            items,
            valid_targets=valid_targets,
            reject_unreferenced_targets=bool(
                cfg.get("reject_unreferenced_targets", True)
            ),
        )
        atomic_write_json(
            candidates_dir / f"candidate_{index:04d}.json",
            result,
        )
        candidate_batches.append(result)

    if len(candidate_batches) == 1:
        merged = candidate_batches[0]
    else:
        merge_user = render(
            str(merge_prompt["user"]),
            "CANDIDATES_JSON",
            json.dumps(
                candidate_batches,
                ensure_ascii=False,
                indent=2,
            ),
        )
        merged = provider.generate_json(
            system=str(merge_prompt["system"]),
            user=merge_user,
        )

    raw_items = merged.get("items")
    if not isinstance(raw_items, list):
        raise StageError("completion merge 返回 items 非 list。")

    supplements = validate_completion_items(
        raw_items,
        valid_targets=valid_targets,
        reject_unreferenced_targets=bool(
            cfg.get("reject_unreferenced_targets", True)
        ),
    )

    # Preserve all reconstructed source content exactly; only replace supplements.
    lecture["supplements"] = supplements
    # Completion invalidates all downstream semantic/render/audit conclusions.
    lecture["review"] = {"issues": []}
    lecture.pop("audit", None)
    lecture["stage"] = "completion_draft"

    atomic_write_json(lecture_path, lecture)
    atomic_write_json(
        completion_dir / "completion.json",
        {
            "schema_version": "1.0",
            "items": supplements,
        },
    )

    reason_counts = {
        reason: sum(1 for item in supplements if item["reason"] == reason)
        for reason in sorted({
            "missing_content",
            "incomplete_explanation",
            "unclear_explanation",
            "pedagogical_bridge",
        })
    }

    derived_targets = {str(x.get("target_id", "")) for x in supplements if isinstance(x, dict) and x.get("type") == "derived_solution"}
    required_incomplete = [str(p.get("id", "")) for p in lecture.get("problems", []) if isinstance(p, dict) and infer_requires_solution(p) and infer_solution_completeness(p) in {"incomplete", "missing", "uncertain"}]
    unresolved = [pid for pid in required_incomplete if pid not in derived_targets]

    report = {
        "schema_version": "1.0",
        "stage": "completion",
        "chunks": len(chunks),
        "candidate_batches": len(candidate_batches),
        "supplements": len(supplements),
        "derived_solutions": sum(1 for x in supplements if x.get("type") == "derived_solution"),
        "reasons": reason_counts,
        "prompt_versions": {
            "analyze": str(analyze_prompt.get("version", "unknown")),
            "merge": str(merge_prompt.get("version", "unknown")),
        },
        "llm": {
            "provider": cfg.get("llm", {}).get("provider"),
            "model": cfg.get("llm", {}).get("model"),
        },
        "quality": {"complete": not unresolved, "unresolved_solution_targets": unresolved},
        "output": str(lecture_path),
    }
    atomic_write_json(
        ctx.workspace_root / "reports" / "completion_report.json",
        report,
    )

    logger.info(
        "[completion] supplements=%d",
        len(supplements),
    )
