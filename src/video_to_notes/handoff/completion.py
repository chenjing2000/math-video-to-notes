from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..completion.chunking import make_completion_chunks
from ..completion.assessment import infer_requires_solution, infer_solution_completeness
from ..completion.validation import collect_valid_targets, validate_completion_items
from ..config import resolve_resource_path
from ..errors import StageError
from ..reconstruction.prompts import load_prompts, render
from ..reconstruction.figures import bind_problem_figures
from ..util import atomic_write_json, read_json
from ..receipt import request_id
from .model_routing import resolve_required_model, resolved_model_routing
from .common import (
    ensure_clean_dir,
    load_response,
    response_root,
    task_root,
    write_instructions,
    write_task_file,
    require_request_id,
)


def _project_root(config: dict[str, Any]) -> Path:
    configured = config.get("project", {}).get("project_root")
    return Path(str(configured)).expanduser().resolve() if configured else Path.cwd().resolve()


def prepare_completion(*, workspace_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    cfg = config["completion"]
    rid = request_id(workspace_root, config, "completion")
    required_model = resolve_required_model(config, "completion")
    lecture_path = workspace_root / "lecture" / "lecture.json"
    if not lecture_path.exists():
        raise StageError("缺少 lecture.json，请先完成 reconstruction apply。")
    lecture = read_json(lecture_path)
    if lecture.get("stage") not in {"reconstruction_draft", "completion_draft", "review_draft", "rendered", "audited"}:
        raise StageError("completion prepare 可从 reconstruction_draft/completion_draft/review_draft/rendered/audited 重新开始。")

    timeline_path = workspace_root / "evidence" / "timeline.json"
    if timeline_path.exists():
        timeline_data = read_json(timeline_path)
        timeline = timeline_data.get("timeline", []) if isinstance(timeline_data, dict) else []
        if isinstance(timeline, list):
            bind_problem_figures(
                lecture,
                timeline,
                workspace_root=workspace_root,
                infer_from_statement=bool(config.get("reconstruction", {}).get("infer_problem_figures", True)),
                max_figures_per_problem=int(config.get("reconstruction", {}).get("max_figures_per_problem", 2)),
            )
            atomic_write_json(lecture_path, lecture)

    project_root = _project_root(config)
    prompt_path = resolve_resource_path(cfg.get("prompts_file", "package:prompts.yaml"), default_name="prompts.yaml")
    prompts = load_prompts(prompt_path.resolve()).get("completion", {})
    analyze = prompts.get("analyze", {})
    merge = prompts.get("merge", {})
    if not isinstance(analyze, dict) or not isinstance(merge, dict):
        raise StageError("prompts.yaml 缺少 completion.analyze/merge。")

    chunks = make_completion_chunks(
        lecture,
        max_items_per_call=int(cfg.get("max_items_per_call", 12)),
    )
    tasks = task_root(workspace_root, "completion")
    responses = response_root(workspace_root, "completion")
    ensure_clean_dir(tasks)
    ensure_clean_dir(responses)

    for index, chunk in enumerate(chunks):
        user = render(
            str(analyze["user"]),
            "LECTURE_JSON",
            json.dumps({"items": chunk.get("items", [])}, ensure_ascii=False, indent=2),
        )
        write_task_file(tasks / f"chunk_{index:04d}.request.json", {
            "schema_version": "1.0",
            "request_id": rid,
            "task_type": "completion_chunk",
            "required_model": required_model,
            "chunk_index": index,
            "system": str(analyze["system"]),
            "user": user,
            "output_file": f"responses/completion/chunk_{index:04d}.json",
        })

    write_task_file(tasks / "merge.request.json", {
        "schema_version": "1.0",
        "task_type": "completion_merge",
        "required_model": required_model,
        "system": str(merge["system"]),
        "user_template": str(merge["user"]),
        "input_files": [f"responses/completion/chunk_{i:04d}.json" for i in range(len(chunks))],
        "output_file": "responses/completion/completion.json",
    })
    manifest = {
        "schema_version": "1.0",
        "request_id": rid,
        "stage": "completion",
        "mode": "codex_handoff",
        "required_model": required_model,
        "model_routing": resolved_model_routing(config),
        "chunks": len(chunks),
        "valid_targets": sorted(collect_valid_targets(lecture)),
        "required_outputs": [
            *[f"chunk_{i:04d}.json" for i in range(len(chunks))],
            "completion.json",
        ],
    }
    write_task_file(tasks / "manifest.json", manifest)
    write_instructions(tasks / "INSTRUCTIONS.md", f"""# Codex Handoff — Pedagogical Completion

本阶段要求模型：`{required_model}`。如果当前 Codex 会话不是该模型，请先切换到该模型再处理。

处理所有 `chunk_XXXX.request.json`，把响应写到 `responses/completion/`，然后按 `merge.request.json` 合并为 `completion.json`。

硬规则：
- 每个响应 JSON 必须原样回显对应 request 中的 `request_id`。
- 只能做当前课程所需的教学补充，但“老师没有讲完”不是停止推导的理由。
- 对 `requires_solution=true` 且 `solution_completeness=incomplete/missing/uncertain` 的题，只要题目条件足够，必须生成 `type=derived_solution` 的完整补充证明/解答。
- derived_solution 要连续推导并说明非显然步骤，不得只给结论或“类似可得”。
- reason 仅允许 `missing_content`、`incomplete_explanation`、`unclear_explanation`、`pedagogical_bridge`。
- 每项必须有真实 `target_id`、`type`、`why_needed`、`content`。
- 数学符号用标准 LaTeX，不用 Unicode 数学特殊符号。
- 不得修改老师原题、原解、原答案；新增证明始终是讲义 supplement。
- 只有确实无需补充时才返回空 `items`。

本任务共有 {len(chunks)} 个 chunk。完成后执行 `video-to-notes complete apply VIDEO`。
""")
    return manifest


def apply_completion(*, workspace_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    cfg = config["completion"]
    lecture_path = workspace_root / "lecture" / "lecture.json"
    if not lecture_path.exists():
        raise StageError("缺少 lecture.json。")
    lecture = read_json(lecture_path)
    valid_targets = collect_valid_targets(lecture)
    manifest_path = task_root(workspace_root, "completion") / "manifest.json"
    if not manifest_path.exists():
        raise StageError("尚未 prepare completion task。")
    manifest = read_json(manifest_path)
    chunks = int(manifest.get("chunks", 0))
    responses = response_root(workspace_root, "completion")

    for index in range(chunks):
        raw = load_response(responses / f"chunk_{index:04d}.json", f"completion chunk {index}")
        require_request_id(raw, str(manifest.get("request_id", "")), f"completion chunk {index}")
        validate_completion_items(
            raw.get("items"),
            valid_targets=valid_targets,
            reject_unreferenced_targets=bool(cfg.get("reject_unreferenced_targets", True)),
        )

    merged = load_response(responses / "completion.json", "completion merge")
    require_request_id(merged, str(manifest.get("request_id", "")), "completion merge")
    supplements = validate_completion_items(
        merged.get("items"),
        valid_targets=valid_targets,
        reject_unreferenced_targets=bool(cfg.get("reject_unreferenced_targets", True)),
    )
    lecture["supplements"] = supplements
    # Completion invalidates all downstream semantic/render/audit conclusions.
    lecture["review"] = {"issues": []}
    lecture.pop("audit", None)
    lecture["stage"] = "completion_draft"
    atomic_write_json(lecture_path, lecture)
    out_dir = workspace_root / "lecture" / "completion"
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "completion.json", {"schema_version": "1.0", "items": supplements})
    derived_targets = {str(x.get("target_id", "")) for x in supplements if isinstance(x, dict) and x.get("type") == "derived_solution"}
    required_incomplete = [str(p.get("id", "")) for p in lecture.get("problems", []) if isinstance(p, dict) and infer_requires_solution(p) and infer_solution_completeness(p) in {"incomplete", "missing", "uncertain"}]
    unresolved = [pid for pid in required_incomplete if pid not in derived_targets]
    report = {
        "schema_version": "1.0",
        "stage": "completion",
        "mode": "codex_handoff",
        "chunks": chunks,
        "supplements": len(supplements),
        "derived_solutions": sum(1 for x in supplements if x.get("type") == "derived_solution"),
        "quality": {"complete": not unresolved, "unresolved_solution_targets": unresolved},
        "output": str(lecture_path),
    }
    atomic_write_json(workspace_root / "reports" / "completion_report.json", report)
    return report
