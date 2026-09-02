from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..completion.assessment import infer_requires_solution, infer_solution_completeness
from ..completion.chunking import make_completion_chunks
from ..completion.validation import collect_valid_targets, validate_completion_items
from ..config import resolve_resource_path
from ..errors import StageError
from ..performance import record_handoff_apply, record_handoff_prepare
from ..receipt import request_id
from ..reconstruction.figures import bind_problem_figures
from ..reconstruction.prompts import load_prompts, render
from ..util import atomic_write_json, read_json, stable_json_hash
from .common import (
    load_response,
    manifest_request_id,
    prepare_task_directories,
    response_root,
    task_root,
    write_instructions,
    write_task_file,
    require_request_id,
)
from .model_routing import resolve_required_model, resolved_model_routing


def _project_root(config: dict[str, Any]) -> Path:
    configured = config.get("project", {}).get("project_root")
    return Path(str(configured)).expanduser().resolve() if configured else Path.cwd().resolve()


def _chunk_source_ids(chunk: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for item in chunk.get("items", []):
        if isinstance(item, dict):
            value = str(item.get("id", ""))
            if value and value not in out:
                out.append(value)
    return out


def prepare_completion(*, workspace_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    cfg = config["completion"]
    input_id = request_id(workspace_root, config, "completion")
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

    prompt_path = resolve_resource_path(cfg.get("prompts_file", "package:prompts.yaml"), default_name="prompts.yaml")
    prompts = load_prompts(prompt_path.resolve()).get("completion", {})
    analyze = prompts.get("analyze", {})
    merge = prompts.get("merge", {})
    if not isinstance(analyze, dict) or not isinstance(merge, dict):
        raise StageError("prompts.yaml 缺少 completion.analyze/merge。")

    chunks = make_completion_chunks(lecture, max_items_per_call=int(cfg.get("max_items_per_call", 12)))
    valid_targets = collect_valid_targets(lecture)
    requests: dict[str, dict[str, Any]] = {}
    reusable: dict[str, tuple[str, Any]] = {}
    chunk_request_ids: list[str] = []

    def validate_items_response(data: dict[str, Any]) -> None:
        validate_completion_items(
            data.get("items"),
            valid_targets=valid_targets,
            reject_unreferenced_targets=bool(cfg.get("reject_unreferenced_targets", True)),
        )

    for index, chunk in enumerate(chunks):
        payload = {"items": chunk.get("items", [])}
        user = render(str(analyze["user"]), "LECTURE_JSON", json.dumps(payload, ensure_ascii=False, indent=2))
        rid = request_id(workspace_root, config, "completion", extra={
            "task_type": "completion_chunk",
            "chunk_index": index,
            "model": required_model,
            "system": str(analyze["system"]),
            "user_hash": stable_json_hash(user),
        })
        chunk_request_ids.append(rid)
        output_name = f"chunk_{index:04d}.json"
        request = {
            "schema_version": "1.1",
            "request_id": rid,
            "task_type": "completion_chunk",
            "required_model": required_model,
            "chunk_index": index,
            "system": str(analyze["system"]),
            "user": user,
            "packet_provenance": {"source_ids": _chunk_source_ids(chunk), "frame_ids": []},
            "output_file": f"responses/completion/{output_name}",
        }
        requests[output_name] = request
        reusable[output_name] = (rid, validate_items_response)

    merge_rid = request_id(workspace_root, config, "completion", extra={
        "task_type": "completion_merge",
        "model": required_model,
        "system": str(merge["system"]),
        "user_template": str(merge["user"]),
        "chunk_request_ids": chunk_request_ids,
    })
    merge_request = {
        "schema_version": "1.1",
        "request_id": merge_rid,
        "task_type": "completion_merge",
        "required_model": required_model,
        "system": str(merge["system"]),
        "user_template": str(merge["user"]),
        "input_files": [f"responses/completion/chunk_{i:04d}.json" for i in range(len(chunks))],
        "input_request_ids": chunk_request_ids,
        "packet_provenance": {"source_ids": sorted(valid_targets), "frame_ids": []},
        "output_file": "responses/completion/completion.json",
    }
    requests["completion.json"] = merge_request
    reusable["completion.json"] = (merge_rid, validate_items_response)

    tasks = task_root(workspace_root, "completion")
    responses = response_root(workspace_root, "completion")
    reused = prepare_task_directories(tasks, responses, reusable=reusable)
    # A merge response is reusable only when every chunk response it was based on
    # was also preserved. If any chunk must be regenerated, force a new merge.
    chunk_outputs = {f"chunk_{i:04d}.json" for i in range(len(chunks))}
    if not chunk_outputs.issubset(reused):
        (responses / "completion.json").unlink(missing_ok=True)
        reused.discard("completion.json")

    for output_name, request in requests.items():
        filename = "merge.request.json" if output_name == "completion.json" else output_name.replace(".json", ".request.json")
        write_task_file(tasks / filename, request)

    manifest = {
        "schema_version": "1.1",
        "input_id": input_id,
        "request_id": input_id,
        "stage": "completion",
        "mode": "codex_handoff",
        "required_model": required_model,
        "model_routing": resolved_model_routing(config),
        "chunks": len(chunks),
        "valid_targets": sorted(valid_targets),
        "requests": {
            output: {
                "request_id": str(req["request_id"]),
                "request_file": "merge.request.json" if output == "completion.json" else output.replace(".json", ".request.json"),
            }
            for output, req in requests.items()
        },
        "required_outputs": list(requests.keys()),
        "reused_outputs": sorted(reused),
    }
    write_task_file(tasks / "manifest.json", manifest)
    record_handoff_prepare(workspace_root, "completion", input_id=input_id, requests=requests, reused_outputs=reused, warning_thresholds=config.get("performance", {}).get("packet_warning_chars", {}))

    write_instructions(tasks / "INSTRUCTIONS.md", f"""# Codex Handoff — Pedagogical Completion

本阶段要求模型：`{required_model}`。只处理尚未有合法 response 的 request；已有 request_id 完全一致的 response 直接复用。

硬规则：
- 每个响应 JSON 必须原样回显**该 request 自己的** `request_id`。
- 对 `requires_solution=true` 且 `solution_completeness=incomplete/missing/uncertain` 的题，只要题目条件足够，必须生成 `type=derived_solution` 的完整补充证明/解答。
- derived_solution 要连续推导并说明非显然步骤，不得只给结论或“类似可得”。
- reason 仅允许 `missing_content`、`incomplete_explanation`、`unclear_explanation`、`pedagogical_bridge`。
- 不得修改老师原题、原解、原答案；新增证明始终是讲义 supplement。
- 数学符号使用标准 LaTeX。

本任务共有 {len(chunks)} 个 chunk；prepare 已复用 {len(reused)} 个合法 response。
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
        name = f"chunk_{index:04d}.json"
        raw = load_response(responses / name, f"completion chunk {index}")
        require_request_id(raw, manifest_request_id(manifest, name), f"completion chunk {index}")
        validate_completion_items(raw.get("items"), valid_targets=valid_targets, reject_unreferenced_targets=bool(cfg.get("reject_unreferenced_targets", True)))

    merged = load_response(responses / "completion.json", "completion merge")
    require_request_id(merged, manifest_request_id(manifest, "completion.json"), "completion merge")
    supplements = validate_completion_items(merged.get("items"), valid_targets=valid_targets, reject_unreferenced_targets=bool(cfg.get("reject_unreferenced_targets", True)))
    lecture["supplements"] = supplements
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
    record_handoff_apply(workspace_root, "completion", responses)
    return report
