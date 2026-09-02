from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Callable

from ..errors import StageError
from ..performance import record_handoff_apply, record_handoff_prepare
from ..receipt import request_id
from ..review.common import (
    empty_math_summary,
    factual_inputs,
    finalize_review,
    load_review_materials,
    render_factual_user,
    render_pedagogical_user,
)
from ..review.evidence_support import collect_evidence_ids_from_targets, select_evidence
from ..review.math_core import (
    apply_math_review_cascade,
    collect_math_review_targets,
    factual_context_for_problem,
    filter_target_for_ids,
    render_math_user,
    select_math_image_paths,
    unresolved_target_ids,
    validate_math_revision_response,
)
from ..review.routing import collect_all_target_ids
from ..review.validation import validate_raw_issues
from ..util import atomic_write_json, read_json, stable_json_hash
from .common import (
    load_response,
    manifest_request_id,
    prepare_task_directories,
    response_matches_request,
    response_root,
    task_root,
    write_instructions,
    write_task_file,
    require_request_id,
)
from .model_routing import resolve_required_model, resolved_model_routing


def _target_ids(items: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        value = str(item.get("target_id", ""))
        if value and value not in out:
            out.append(value)
        for solution in item.get("solutions", []):
            if isinstance(solution, dict):
                sid = str(solution.get("target_id", ""))
                if sid and sid not in out:
                    out.append(sid)
        answer = item.get("answer")
        if isinstance(answer, dict):
            aid = str(answer.get("target_id", ""))
            if aid and aid not in out:
                out.append(aid)
    return out


def _safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return text or "problem"


def _read_valid_response(
    path: Path,
    request_id_value: str,
    validator: Callable[[dict[str, Any]], Any],
) -> Any | None:
    if not response_matches_request(path, request_id_value):
        return None
    try:
        raw = read_json(path)
        if not isinstance(raw, dict):
            return None
        return validator(raw)
    except Exception:
        return None


def _issue_validator(
    *,
    review_type: str,
    valid_target_ids: set[str],
    reject_unknown: bool,
) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    return lambda data: validate_raw_issues(
        data.get("issues"),
        review_type=review_type,
        valid_target_ids=valid_target_ids,
        reject_unreferenced_targets=reject_unknown,
    )


def _factual_request(
    *,
    workspace_root: Path,
    config: dict[str, Any],
    prompts: dict[str, Any],
    targets: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = prompts.get("factual", {})
    user = render_factual_user(prompt, targets, evidence)
    model = resolve_required_model(config, "factual")
    rid = request_id(workspace_root, config, "review", extra={
        "task_type": "review_factual",
        "model": model,
        "system": str(prompt["system"]),
        "user_hash": stable_json_hash(user),
    })
    return {
        "schema_version": "1.3",
        "request_id": rid,
        "task_type": "review_factual",
        "required_model": model,
        "system": str(prompt["system"]),
        "user": user,
        "packet_provenance": {
            "source_ids": _target_ids(targets),
            "frame_ids": sorted({str(fid) for item in evidence for fid in item.get("frame_ids", [])}),
        },
        "output_file": "responses/review/factual.json",
    }


def _math_request(
    *,
    workspace_root: Path,
    config: dict[str, Any],
    prompt: dict[str, Any],
    target: dict[str, Any],
    evidence: list[dict[str, Any]],
    factual_issues: list[dict[str, Any]],
    image_paths: list[str],
    level: str,
    medium_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_type = "review_math" if level == "medium" else "review_math_high"
    routing_type = "math" if level == "medium" else "math_high"
    model = resolve_required_model(config, routing_type)
    user = render_math_user(
        prompt,
        target,
        evidence=evidence,
        factual_issues=factual_issues,
        image_paths=image_paths,
    )
    extra: dict[str, Any] = {
        "task_type": task_type,
        "problem_id": str(target.get("target_id", "")),
        "model": model,
        "system": str(prompt["system"]),
        "user_hash": stable_json_hash(user),
        "image_paths": image_paths,
    }
    if medium_result is not None:
        extra["medium_result_hash"] = stable_json_hash(medium_result)
    rid = request_id(workspace_root, config, "review", extra=extra)
    return {
        "schema_version": "1.3",
        "request_id": rid,
        "task_type": task_type,
        "problem_id": str(target.get("target_id", "")),
        "review_level": level,
        "required_model": model,
        "system": str(prompt["system"]),
        "user": user,
        "image_paths": image_paths,
        "packet_provenance": {
            "source_ids": _target_ids([target]),
            "frame_ids": sorted({str(fid) for item in evidence for fid in item.get("frame_ids", [])}),
            "image_paths": image_paths,
        },
    }


def _pedagogical_request(
    *,
    workspace_root: Path,
    config: dict[str, Any],
    prompt: dict[str, Any],
    lecture: dict[str, Any],
    valid_target_ids: set[str],
) -> dict[str, Any]:
    user = render_pedagogical_user(prompt, lecture)
    model = resolve_required_model(config, "pedagogical")
    rid = request_id(workspace_root, config, "review", extra={
        "task_type": "review_pedagogical",
        "model": model,
        "system": str(prompt["system"]),
        "user_hash": stable_json_hash(user),
    })
    return {
        "schema_version": "1.3",
        "request_id": rid,
        "task_type": "review_pedagogical",
        "required_model": model,
        "system": str(prompt["system"]),
        "user": user,
        "packet_provenance": {"source_ids": sorted(valid_target_ids), "frame_ids": []},
        "output_file": "responses/review/pedagogical.json",
    }


def prepare_review(*, workspace_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Prepare the next cumulative Codex review phase.

    Phases are intentionally sequential:
      factual -> per-problem Sol Medium -> unresolved-target Sol High -> pedagogical.
    Existing valid responses are preserved, so rerunning the one-shot workflow only asks
    Codex for newly required request files.
    """
    cfg = config["review"]
    input_id = request_id(workspace_root, config, "review")
    lecture_path, lecture, timeline, prompts, valid_target_ids, reject_unknown = load_review_materials(
        workspace_root, config
    )
    # Persist deterministic figure binding so later phases and render see the same view.
    atomic_write_json(lecture_path, lecture)
    responses = response_root(workspace_root, "review")
    requests: dict[str, dict[str, Any]] = {}
    validators: dict[str, Callable[[dict[str, Any]], Any]] = {}
    phase = "ready"

    # Phase 1: factual. Math packets are not prepared until this response is valid.
    factual_issues: list[dict[str, Any]] = []
    factual_cfg = cfg.get("factual", {})
    if bool(factual_cfg.get("enabled", True)):
        factual_targets, factual_evidence = factual_inputs(lecture, timeline, factual_cfg)
        if factual_targets:
            req = _factual_request(
                workspace_root=workspace_root,
                config=config,
                prompts=prompts,
                targets=factual_targets,
                evidence=factual_evidence,
            )
            requests["factual.json"] = req
            validator = _issue_validator(review_type="factual", valid_target_ids=valid_target_ids, reject_unknown=reject_unknown)
            validators["factual.json"] = validator
            factual_issues_value = _read_valid_response(responses / "factual.json", str(req["request_id"]), validator)
            if factual_issues_value is None:
                phase = "factual"
            else:
                factual_issues = factual_issues_value

    math_targets = collect_math_review_targets(lecture) if bool(cfg.get("math", {}).get("enabled", True)) else []
    medium_results: dict[str, dict[str, Any]] = {}
    high_results: dict[str, dict[str, Any]] = {}
    math_output_map: dict[str, dict[str, str]] = {}
    max_images = int(cfg.get("math", {}).get("max_images_per_problem", 2))

    # Phase 2: one Sol Medium request per problem, only after factual is ready.
    if phase != "factual" and math_targets:
        medium_missing = False
        for target in math_targets:
            pid = str(target.get("target_id", ""))
            safe = _safe_id(pid)
            evidence_ids = collect_evidence_ids_from_targets([target])
            evidence = select_evidence(timeline, evidence_ids=evidence_ids)
            images = select_math_image_paths(
                lecture, target, timeline, workspace_root=workspace_root, max_images=max_images
            )
            factual_context = factual_context_for_problem(factual_issues, pid)
            prompt = prompts.get("math", {})
            req = _math_request(
                workspace_root=workspace_root,
                config=config,
                prompt=prompt,
                target=target,
                evidence=evidence,
                factual_issues=factual_context,
                image_paths=images,
                level="medium",
            )
            name = f"math_{safe}_medium.json"
            req["output_file"] = f"responses/review/{name}"
            requests[name] = req
            validator = lambda data, t=target: validate_math_revision_response(data, [t])
            validators[name] = validator
            normalized = _read_valid_response(responses / name, str(req["request_id"]), validator)
            math_output_map.setdefault(pid, {})["medium"] = name
            if normalized is None:
                medium_missing = True
            else:
                medium_results[pid] = normalized
        if medium_missing:
            phase = "math_medium"

    # Phase 3: only unresolved targets escalate to Sol High.
    if phase not in {"factual", "math_medium"} and math_targets:
        high_missing = False
        for target in math_targets:
            pid = str(target.get("target_id", ""))
            medium = medium_results.get(pid)
            if medium is None:
                raise StageError(f"review prepare 缺少已验证的 Medium 结果: {pid}")
            unresolved = unresolved_target_ids(medium)
            if not unresolved:
                continue
            high_target = filter_target_for_ids(target, unresolved)
            evidence_ids = collect_evidence_ids_from_targets([target])
            evidence = select_evidence(timeline, evidence_ids=evidence_ids)
            images = select_math_image_paths(
                lecture, target, timeline, workspace_root=workspace_root, max_images=max_images
            )
            factual_context = factual_context_for_problem(factual_issues, pid)
            prompt = prompts.get("math_high", {})
            req = _math_request(
                workspace_root=workspace_root,
                config=config,
                prompt=prompt,
                target=high_target,
                evidence=evidence,
                factual_issues=factual_context,
                image_paths=images,
                level="high",
                medium_result=medium,
            )
            safe = _safe_id(pid)
            name = f"math_{safe}_high.json"
            req["output_file"] = f"responses/review/{name}"
            requests[name] = req
            validator = lambda data, t=high_target: validate_math_revision_response(data, [t])
            validators[name] = validator
            normalized = _read_valid_response(responses / name, str(req["request_id"]), validator)
            math_output_map.setdefault(pid, {})["high"] = name
            if normalized is None:
                high_missing = True
            else:
                high_results[pid] = normalized
        if high_missing:
            phase = "math_high"

    # Build the publication view before pedagogical review so it sees the actual final notes.
    projected_lecture = deepcopy(lecture)
    if phase not in {"factual", "math_medium", "math_high"} and math_targets:
        apply_math_review_cascade(
            projected_lecture,
            math_targets,
            medium_results=medium_results,
            high_results=high_results,
        )

    # Phase 4: pedagogical review sees the publication-oriented math result.
    pedagogical_cfg = cfg.get("pedagogical", {})
    if phase not in {"factual", "math_medium", "math_high"} and bool(pedagogical_cfg.get("enabled", True)) and bool(pedagogical_cfg.get("whole_lecture", True)):
        req = _pedagogical_request(
            workspace_root=workspace_root,
            config=config,
            prompt=prompts.get("pedagogical", {}),
            lecture=projected_lecture,
            valid_target_ids=valid_target_ids,
        )
        requests["pedagogical.json"] = req
        validator = _issue_validator(review_type="pedagogical", valid_target_ids=valid_target_ids, reject_unknown=reject_unknown)
        validators["pedagogical.json"] = validator
        if _read_valid_response(responses / "pedagogical.json", str(req["request_id"]), validator) is None:
            phase = "pedagogical"

    tasks = task_root(workspace_root, "review")
    reusable = {name: (str(req["request_id"]), validators.get(name)) for name, req in requests.items()}
    reused = prepare_task_directories(tasks, responses, reusable=reusable)
    for output_name, request in requests.items():
        write_task_file(tasks / output_name.replace(".json", ".request.json"), request)

    manifest = {
        "schema_version": "1.3",
        "input_id": input_id,
        "request_id": input_id,
        "stage": "review",
        "phase": phase,
        "mode": "codex_handoff",
        "model_routing": resolved_model_routing(config),
        "required_outputs": list(requests.keys()),
        "requests": {
            output: {
                "request_id": str(req["request_id"]),
                "request_file": output.replace(".json", ".request.json"),
                "task_type": str(req.get("task_type", "")),
                "problem_id": req.get("problem_id"),
                "review_level": req.get("review_level"),
            }
            for output, req in requests.items()
        },
        "math_outputs": math_output_map,
        "reused_outputs": sorted(reused),
        "valid_target_ids": sorted(valid_target_ids),
    }
    write_task_file(tasks / "manifest.json", manifest)
    record_handoff_prepare(
        workspace_root,
        "review",
        input_id=input_id,
        requests=requests,
        reused_outputs=reused,
        warning_thresholds=config.get("performance", {}).get("packet_warning_chars", {}),
    )

    write_instructions(tasks / "INSTRUCTIONS.md", f"""# Codex Handoff — Review v1.2.4

当前阶段：`{phase}`。处理本目录中所有尚未有合法 response 的 `*.request.json`；已有 request_id 完全一致的响应必须复用。

固定顺序：
1. factual → `luna-high`
2. 每道有解题过程的题 → `sol-medium`
3. 仅 Medium unresolved 的 target → `sol-high`
4. pedagogical → `terra`

数学规则：
- 只要有解题过程就必须经过 Sol Medium。
- verified 不重写原文；revised 直接给完整修正版；unresolved 不猜测。
- teacher_solution 不完整时，Sol 只审已有部分，不替老师补完；完整补充仍来自 Completion derived_solution。
- Sol High 只处理 Medium unresolved target，不重做已解决 target。
- Sol High 仍 unresolved 时，最终 PDF 仍正常生成，并在该题仅注明一次：`本题 GPT sol 未处理完成。`
- 几何题必须实际查看 request 中的 `image_paths`。
- 每个 response 必须原样回显其 request 的 `request_id`。

本次 prepare 已复用 {len(reused)} 个合法 response。
""")
    return manifest


def apply_review(*, workspace_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    cfg = config["review"]
    lecture_path = workspace_root / "lecture" / "lecture.json"
    if not lecture_path.exists():
        raise StageError("缺少 lecture.json。")
    lecture = read_json(lecture_path)
    valid = collect_all_target_ids(lecture)
    manifest_path = task_root(workspace_root, "review") / "manifest.json"
    if not manifest_path.exists():
        raise StageError("尚未 prepare review task。")
    manifest = read_json(manifest_path)
    if str(manifest.get("phase")) != "ready":
        raise StageError(f"review handoff 尚未完成全部阶段，当前 phase={manifest.get('phase')}")

    responses = response_root(workspace_root, "review")
    reject_unknown = bool(cfg.get("reject_unreferenced_targets", True))
    all_issues: list[dict[str, Any]] = []

    if "factual.json" in manifest.get("required_outputs", []):
        raw = load_response(responses / "factual.json", "factual review")
        require_request_id(raw, manifest_request_id(manifest, "factual.json"), "factual review")
        all_issues.extend(validate_raw_issues(
            raw.get("issues"),
            review_type="factual",
            valid_target_ids=valid,
            reject_unreferenced_targets=reject_unknown,
        ))

    math_targets = collect_math_review_targets(lecture)
    medium_results: dict[str, dict[str, Any]] = {}
    high_results: dict[str, dict[str, Any]] = {}
    math_outputs = manifest.get("math_outputs", {}) if isinstance(manifest.get("math_outputs"), dict) else {}
    for target in math_targets:
        pid = str(target.get("target_id", ""))
        entries = math_outputs.get(pid, {}) if isinstance(math_outputs.get(pid), dict) else {}
        medium_name = str(entries.get("medium", ""))
        if not medium_name:
            raise StageError(f"review manifest 缺少 {pid} 的 Sol Medium 输出。")
        raw = load_response(responses / medium_name, f"{pid} Sol Medium review")
        require_request_id(raw, manifest_request_id(manifest, medium_name), f"{pid} Sol Medium review")
        medium_results[pid] = validate_math_revision_response(raw, [target])
        unresolved = unresolved_target_ids(medium_results[pid])
        if unresolved:
            high_name = str(entries.get("high", ""))
            if not high_name:
                raise StageError(f"review manifest 缺少 {pid} unresolved target 的 Sol High 输出。")
            high_target = filter_target_for_ids(target, unresolved)
            high_raw = load_response(responses / high_name, f"{pid} Sol High review")
            require_request_id(high_raw, manifest_request_id(manifest, high_name), f"{pid} Sol High review")
            high_results[pid] = validate_math_revision_response(high_raw, [high_target])

    math_summary = empty_math_summary()
    if math_targets:
        math_summary = apply_math_review_cascade(
            lecture,
            math_targets,
            medium_results=medium_results,
            high_results=high_results,
        )

    if "pedagogical.json" in manifest.get("required_outputs", []):
        raw = load_response(responses / "pedagogical.json", "pedagogical review")
        require_request_id(raw, manifest_request_id(manifest, "pedagogical.json"), "pedagogical review")
        all_issues.extend(validate_raw_issues(
            raw.get("issues"),
            review_type="pedagogical",
            valid_target_ids=valid,
            reject_unreferenced_targets=reject_unknown,
        ))

    report = finalize_review(
        workspace_root=workspace_root,
        lecture_path=lecture_path,
        lecture=lecture,
        raw_issues=all_issues,
        math_summary=math_summary,
        mode="codex_handoff",
    )
    record_handoff_apply(workspace_root, "review", responses)
    return report
