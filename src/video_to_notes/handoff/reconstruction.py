from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import resolve_resource_path
from ..errors import StageError
from ..reconstruction.chunking import chunk_evidence
from ..reconstruction.prompts import load_prompts, render
from ..reconstruction.stage import _compact_evidence, _enrich_metadata, _load_timeline
from ..reconstruction.validation import validate_chunk, validate_lecture_draft
from ..reconstruction.figures import bind_problem_figures
from ..util import atomic_write_json
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
    if configured:
        return Path(str(configured)).expanduser().resolve()
    return Path.cwd().resolve()


def prepare_reconstruction(
    *, workspace_root: Path, config: dict[str, Any]
) -> dict[str, Any]:
    cfg = config["reconstruction"]
    rid = request_id(workspace_root, config, "reconstruction")
    required_model = resolve_required_model(config, "reconstruction")
    project_root = _project_root(config)
    timeline = _load_timeline(workspace_root / "evidence" / "timeline.json")
    compact = [_compact_evidence(item) for item in timeline]
    chunks = chunk_evidence(
        compact,
        max_chars=int(cfg.get("max_evidence_chars_per_chunk", 28000)),
    )

    prompt_path = resolve_resource_path(cfg.get("prompts_file", "package:prompts.yaml"), default_name="prompts.yaml")
    prompts = load_prompts(prompt_path.resolve())
    recon = prompts.get("reconstruction", {})
    chunk_prompt = recon.get("chunk", {})
    merge_prompt = recon.get("merge", {})
    if not isinstance(chunk_prompt, dict) or not isinstance(merge_prompt, dict):
        raise StageError("prompts.yaml 缺少 reconstruction.chunk/merge。")

    tasks = task_root(workspace_root, "reconstruction")
    responses = response_root(workspace_root, "reconstruction")
    ensure_clean_dir(tasks)
    ensure_clean_dir(responses)

    for index, chunk in enumerate(chunks):
        user = render(
            str(chunk_prompt["user"]),
            "EVIDENCE_JSON",
            json.dumps(chunk, ensure_ascii=False, indent=2),
        )
        write_task_file(
            tasks / f"chunk_{index:04d}.request.json",
            {
                "schema_version": "1.0",
                "request_id": rid,
                "task_type": "reconstruction_chunk",
                "required_model": required_model,
                "chunk_index": index,
                "system": str(chunk_prompt["system"]),
                "user": user,
                "evidence_ids": [str(x.get("id")) for x in chunk],
                "output_file": f"responses/reconstruction/chunk_{index:04d}.json",
            },
        )

    write_task_file(
        tasks / "merge.request.json",
        {
            "schema_version": "1.0",
            "request_id": rid,
            "task_type": "reconstruction_merge",
            "required_model": required_model,
            "system": str(merge_prompt["system"]),
            "user_template": str(merge_prompt["user"]),
            "input_files": [
                f"responses/reconstruction/chunk_{i:04d}.json"
                for i in range(len(chunks))
            ],
            "output_file": "responses/reconstruction/lecture.json",
        },
    )

    manifest = {
        "schema_version": "1.0",
        "request_id": rid,
        "stage": "reconstruction",
        "mode": "codex_handoff",
        "required_model": required_model,
        "model_routing": resolved_model_routing(config),
        "evidence_segments": len(compact),
        "chunks": len(chunks),
        "task_dir": str(tasks),
        "response_dir": str(responses),
        "required_outputs": [
            *[f"chunk_{i:04d}.json" for i in range(len(chunks))],
            "lecture.json",
        ],
    }
    write_task_file(tasks / "manifest.json", manifest)
    write_instructions(
        tasks / "INSTRUCTIONS.md",
        f"""# Codex Handoff — Reconstruction

处理本目录中的 reconstruction 任务，不要调用外部 LLM API。

本阶段要求模型：`{required_model}`。如果当前 Codex 会话不是该模型，请先切换到该模型再处理。

## 执行顺序

1. 依次读取 `chunk_XXXX.request.json`。
2. 严格按照其中的 `system` 与 `user` 完成重构，只输出 JSON。
3. 将每个结果写到工作区 `responses/reconstruction/chunk_XXXX.json`。
4. 读取 `merge.request.json` 和所有 chunk 响应。
5. 将 chunk 响应 JSON 代入 merge prompt 的 `{{{{CHUNKS_JSON}}}}`。
6. 写出最终 `responses/reconstruction/lecture.json`。

## 硬规则

- 每个响应 JSON 必须原样回显对应 request 中的 `request_id`。

- 只能使用 task 中提供的 Evidence。
- Visual-first：request 中每个 Evidence 都带 `frames`（frame id/time/path）。遇到题目图、几何图、板书图时必须实际查看对应图片，再决定 `figure_evidence_ids`，不能只看 transcript。
- 题干出现“如图/图中/下图/图示/见图”时，必须尽量绑定真实 `figure_evidence_ids`。
- 不得虚构 evidence id 或图片路径。
- 每道需要证明/求解的题必须给 `requires_solution` 和 `solution_completeness`；老师没讲完只能标 incomplete，不能由 reconstruction 自行补证明。
- Sprint 5 禁止生成 `origin = supplement`。
- `supplements` 必须为空数组。
- 保留不确定性：无法确认时用 `probable` 或 `uncertain`。
- 不得静默修正老师内容。

完成后不要运行后续 stage；由 `video-to-notes reconstruct apply VIDEO` 验收。

本任务共有 {len(chunks)} 个 chunk。
""",
    )
    return manifest


def apply_reconstruction(
    *, workspace_root: Path, config: dict[str, Any], ctx: Any
) -> dict[str, Any]:
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
        result = load_response(
            responses / f"chunk_{index:04d}.json",
            f"reconstruction chunk {index}",
        )
        require_request_id(result, str(manifest.get("request_id", "")), f"reconstruction chunk {index}")
        validate_chunk(result, valid_ids)

    lecture = load_response(responses / "lecture.json", "reconstruction merge")
    require_request_id(lecture, str(manifest.get("request_id", "")), "reconstruction merge")
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
    return report
