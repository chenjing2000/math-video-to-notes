from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import resolve_resource_path
from ..errors import StageError
from ..performance import record_handoff_apply, record_handoff_prepare
from ..receipt import request_id
from ..reconstruction.chunking import chunk_evidence
from ..reconstruction.figures import bind_problem_figures
from ..reconstruction.prompts import load_prompts, render
from ..reconstruction.stage import _compact_evidence, _enrich_metadata, _load_timeline
from ..reconstruction.validation import validate_chunk, validate_lecture_draft
from ..util import atomic_write_json, stable_json_hash
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
    if configured:
        return Path(str(configured)).expanduser().resolve()
    return Path.cwd().resolve()


def _frame_ids(chunk: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for item in chunk:
        for fid in item.get("frame_ids", []):
            text = str(fid)
            if text and text not in out:
                out.append(text)
    return out


def prepare_reconstruction(*, workspace_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    cfg = config["reconstruction"]
    input_id = request_id(workspace_root, config, "reconstruction")
    required_model = resolve_required_model(config, "reconstruction")
    timeline = _load_timeline(workspace_root / "evidence" / "timeline.json")
    valid_ids = {str(item["id"]) for item in timeline if "id" in item}
    compact = [_compact_evidence(item) for item in timeline]
    chunks = chunk_evidence(compact, max_chars=int(cfg.get("max_evidence_chars_per_chunk", 28000)))

    prompt_path = resolve_resource_path(cfg.get("prompts_file", "package:prompts.yaml"), default_name="prompts.yaml")
    prompts = load_prompts(prompt_path.resolve())
    recon = prompts.get("reconstruction", {})
    chunk_prompt = recon.get("chunk", {})
    merge_prompt = recon.get("merge", {})
    if not isinstance(chunk_prompt, dict) or not isinstance(merge_prompt, dict):
        raise StageError("prompts.yaml 缺少 reconstruction.chunk/merge。")

    requests: dict[str, dict[str, Any]] = {}
    reusable: dict[str, tuple[str, Any]] = {}
    chunk_request_ids: list[str] = []

    for index, chunk in enumerate(chunks):
        user = render(str(chunk_prompt["user"]), "EVIDENCE_JSON", json.dumps(chunk, ensure_ascii=False, indent=2))
        rid = request_id(workspace_root, config, "reconstruction", extra={
            "task_type": "reconstruction_chunk",
            "chunk_index": index,
            "model": required_model,
            "system": str(chunk_prompt["system"]),
            "user_hash": stable_json_hash(user),
        })
        chunk_request_ids.append(rid)
        output_name = f"chunk_{index:04d}.json"
        request = {
            "schema_version": "1.1",
            "request_id": rid,
            "task_type": "reconstruction_chunk",
            "required_model": required_model,
            "chunk_index": index,
            "system": str(chunk_prompt["system"]),
            "user": user,
            "evidence_ids": [str(x.get("id")) for x in chunk],
            "packet_provenance": {
                "source_ids": [str(x.get("id")) for x in chunk],
                "frame_ids": _frame_ids(chunk),
            },
            "output_file": f"responses/reconstruction/{output_name}",
        }
        requests[output_name] = request
        reusable[output_name] = (rid, lambda data, ids=valid_ids: validate_chunk(data, ids))

    merge_rid = request_id(workspace_root, config, "reconstruction", extra={
        "task_type": "reconstruction_merge",
        "model": required_model,
        "system": str(merge_prompt["system"]),
        "user_template": str(merge_prompt["user"]),
        "chunk_request_ids": chunk_request_ids,
    })
    merge_request = {
        "schema_version": "1.1",
        "request_id": merge_rid,
        "task_type": "reconstruction_merge",
        "required_model": required_model,
        "system": str(merge_prompt["system"]),
        "user_template": str(merge_prompt["user"]),
        "input_files": [f"responses/reconstruction/chunk_{i:04d}.json" for i in range(len(chunks))],
        "input_request_ids": chunk_request_ids,
        "packet_provenance": {"source_ids": [str(x.get("id")) for x in compact], "frame_ids": _frame_ids(compact)},
        "output_file": "responses/reconstruction/lecture.json",
    }
    requests["lecture.json"] = merge_request
    reusable["lecture.json"] = (merge_rid, lambda data, ids=valid_ids: validate_lecture_draft(data, ids))

    tasks = task_root(workspace_root, "reconstruction")
    responses = response_root(workspace_root, "reconstruction")
    reused = prepare_task_directories(tasks, responses, reusable=reusable)
    # A merge response is reusable only when every chunk response it was based on
    # was also preserved. If any chunk must be regenerated, force a new merge.
    chunk_outputs = {f"chunk_{i:04d}.json" for i in range(len(chunks))}
    if not chunk_outputs.issubset(reused):
        (responses / "lecture.json").unlink(missing_ok=True)
        reused.discard("lecture.json")

    for output_name, request in requests.items():
        filename = "merge.request.json" if output_name == "lecture.json" else output_name.replace(".json", ".request.json")
        write_task_file(tasks / filename, request)

    manifest_requests = {
        output: {
            "request_id": str(req["request_id"]),
            "request_file": "merge.request.json" if output == "lecture.json" else output.replace(".json", ".request.json"),
        }
        for output, req in requests.items()
    }
    manifest = {
        "schema_version": "1.1",
        "input_id": input_id,
        "request_id": input_id,
        "stage": "reconstruction",
        "mode": "codex_handoff",
        "required_model": required_model,
        "model_routing": resolved_model_routing(config),
        "evidence_segments": len(compact),
        "chunks": len(chunks),
        "task_dir": str(tasks),
        "response_dir": str(responses),
        "requests": manifest_requests,
        "required_outputs": list(requests.keys()),
        "reused_outputs": sorted(reused),
    }
    write_task_file(tasks / "manifest.json", manifest)
    record_handoff_prepare(workspace_root, "reconstruction", input_id=input_id, requests=requests, reused_outputs=reused, warning_thresholds=config.get("performance", {}).get("packet_warning_chars", {}))

    write_instructions(tasks / "INSTRUCTIONS.md", f"""# Codex Handoff — Reconstruction

处理本目录中的 reconstruction 任务，不要调用外部 LLM API。

本阶段要求模型：`{required_model}`。如果当前 Codex 会话不是该模型，请先切换到该模型再处理。

## 执行顺序

1. 只处理尚未有合法 response 的 `chunk_XXXX.request.json`；已存在且 request_id 一致的 response 直接复用。
2. 严格按照 request 中的 `system` 与 `user` 完成重构，只输出 JSON。
3. 响应必须原样回显**该 request 自己的** `request_id`。
4. 所有 chunk 完成后，读取 `merge.request.json` 和 chunk 响应，生成 `responses/reconstruction/lecture.json`。

## 硬规则

- 只能使用 task 中提供的 Evidence。
- Visual-first：遇到题目图、几何图、板书图时必须实际查看对应图片。
- 题干出现“如图/图中/下图/图示/见图”时，必须尽量绑定真实 `figure_evidence_ids`。
- 不得虚构 evidence id 或图片路径。
- 每道需要证明/求解的题必须给 `requires_solution` 和 `solution_completeness`；老师没讲完只能标 incomplete，不能由 reconstruction 自行补证明。
- Reconstruction 禁止生成 `origin = supplement`；`supplements` 必须为空数组。
- 保留不确定性，不得静默修正老师内容。

本任务共有 {len(chunks)} 个 chunk；prepare 已复用 {len(reused)} 个合法 response。
""")
    return manifest


def apply_reconstruction(*, workspace_root: Path, config: dict[str, Any], ctx: Any) -> dict[str, Any]:
    timeline = _load_timeline(workspace_root / "evidence" / "timeline.json")
    valid_ids = {str(item["id"]) for item in timeline if "id" in item}
    tasks = task_root(workspace_root, "reconstruction")
    manifest_path = tasks / "manifest.json"
    if not manifest_path.exists():
        raise StageError("尚未 prepare reconstruction task。")
    from ..util import read_json
    manifest = read_json(manifest_path)
    chunks = int(manifest.get("chunks", 0))
    responses = response_root(workspace_root, "reconstruction")

    for index in range(chunks):
        name = f"chunk_{index:04d}.json"
        result = load_response(responses / name, f"reconstruction chunk {index}")
        require_request_id(result, manifest_request_id(manifest, name), f"reconstruction chunk {index}")
        validate_chunk(result, valid_ids)

    lecture = load_response(responses / "lecture.json", "reconstruction merge")
    require_request_id(lecture, manifest_request_id(manifest, "lecture.json"), "reconstruction merge")
    lecture.pop("request_id", None)
    validate_lecture_draft(lecture, valid_ids)
    _enrich_metadata(lecture, ctx)
    figure_report = bind_problem_figures(
        lecture,
        timeline,
        workspace_root=workspace_root,
        infer_from_statement=bool(config.get("reconstruction", {}).get("infer_problem_figures", True)),
        max_figures_per_problem=int(config.get("reconstruction", {}).get("max_figures_per_problem", 2)),
    )

    lecture_dir = workspace_root / "lecture"
    lecture_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(lecture_dir / "lecture.json", lecture)
    report = {
        "schema_version": "1.0",
        "stage": "reconstruction",
        "mode": "codex_handoff",
        "evidence_segments": len(timeline),
        "chunks": chunks,
        "sections": len(lecture.get("sections", [])),
        "problems": len(lecture.get("problems", [])),
        "figures": figure_report,
        "output": str(lecture_dir / "lecture.json"),
    }
    atomic_write_json(workspace_root / "reports" / "reconstruction_report.json", report)
    record_handoff_apply(workspace_root, "reconstruction", responses)
    return report
