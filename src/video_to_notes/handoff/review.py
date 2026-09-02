from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import resolve_resource_path
from ..errors import StageError
from ..performance import record_handoff_apply, record_handoff_prepare
from ..receipt import request_id
from ..reconstruction.figures import bind_problem_figures
from ..reconstruction.prompts import load_prompts
from ..review.evidence_support import collect_evidence_ids_from_targets, select_evidence
from ..review.routing import collect_all_target_ids, collect_factual_targets, collect_math_targets
from ..review.validation import assign_issue_ids, validate_raw_issues
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


def _target_ids(items: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("id", "target_id"):
            value = str(item.get(key, ""))
            if value and value not in out:
                out.append(value)
    return out


def prepare_review(*, workspace_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    cfg = config["review"]
    input_id = request_id(workspace_root, config, "review")
    lecture_path = workspace_root / "lecture" / "lecture.json"
    timeline_path = workspace_root / "evidence" / "timeline.json"
    if not lecture_path.exists() or not timeline_path.exists():
        raise StageError("review prepare 需要 lecture.json 和 evidence/timeline.json。")
    lecture = read_json(lecture_path)
    if lecture.get("stage") not in {"completion_draft", "review_draft"}:
        raise StageError("review prepare 只接受 completion_draft/review_draft。")
    timeline_data = read_json(timeline_path)
    timeline = timeline_data.get("timeline", [])
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
    prompts = load_prompts(prompt_path.resolve()).get("review", {})
    valid_target_ids = collect_all_target_ids(lecture)
    requests: dict[str, dict[str, Any]] = {}
    validators: dict[str, Any] = {}

    factual_cfg = cfg.get("factual", {})
    if bool(factual_cfg.get("enabled", True)):
        factual_targets = collect_factual_targets(
            lecture,
            trigger_statuses={str(x) for x in factual_cfg.get("trigger_statuses", ["probable", "uncertain", "conflict"])},
            always_review_problem_fields={str(x) for x in factual_cfg.get("always_review_problem_fields", ["statement", "teacher_solution", "teacher_answer"])},
        )
        if factual_targets:
            evidence_ids = collect_evidence_ids_from_targets(factual_targets)
            evidence = select_evidence(timeline, evidence_ids=evidence_ids)
            prompt = prompts.get("factual", {})
            user = str(prompt["user"]).replace("{{TARGETS_JSON}}", json.dumps(factual_targets, ensure_ascii=False, indent=2)).replace("{{EVIDENCE_JSON}}", json.dumps(evidence, ensure_ascii=False, indent=2))
            model = resolve_required_model(config, "factual")
            rid = request_id(workspace_root, config, "review", extra={
                "task_type": "review_factual", "model": model,
                "system": str(prompt["system"]), "user_hash": stable_json_hash(user),
            })
            requests["factual.json"] = {
                "schema_version": "1.1", "request_id": rid, "task_type": "review_factual",
                "required_model": model, "system": str(prompt["system"]), "user": user,
                "packet_provenance": {"source_ids": _target_ids(factual_targets) + sorted(evidence_ids), "frame_ids": []},
                "output_file": "responses/review/factual.json",
            }
            validators["factual.json"] = lambda data: validate_raw_issues(data.get("issues"), review_type="factual", valid_target_ids=valid_target_ids, reject_unreferenced_targets=bool(cfg.get("reject_unreferenced_targets", True)))

    math_cfg = cfg.get("math", {})
    if bool(math_cfg.get("enabled", True)):
        math_targets = collect_math_targets(lecture, review_all_problems=bool(math_cfg.get("review_all_problems", True)))
        if math_targets:
            prompt = prompts.get("math", {})
            user = str(prompt["user"]).replace("{{TARGETS_JSON}}", json.dumps(math_targets, ensure_ascii=False, indent=2))
            model = resolve_required_model(config, "math")
            rid = request_id(workspace_root, config, "review", extra={
                "task_type": "review_math", "model": model,
                "system": str(prompt["system"]), "user_hash": stable_json_hash(user),
            })
            requests["math.json"] = {
                "schema_version": "1.1", "request_id": rid, "task_type": "review_math",
                "required_model": model, "system": str(prompt["system"]), "user": user,
                "packet_provenance": {"source_ids": _target_ids(math_targets), "frame_ids": []},
                "output_file": "responses/review/math.json",
            }
            def validate_math(data: dict[str, Any]) -> None:
                values = data.get("verified_supplements", [])
                if not isinstance(values, list):
                    raise StageError("math review.verified_supplements 必须为 list。")
                validate_raw_issues(data.get("issues"), review_type="math", valid_target_ids=valid_target_ids, reject_unreferenced_targets=bool(cfg.get("reject_unreferenced_targets", True)))
            validators["math.json"] = validate_math

    pedagogical_cfg = cfg.get("pedagogical", {})
    if bool(pedagogical_cfg.get("enabled", True)) and bool(pedagogical_cfg.get("whole_lecture", True)):
        prompt = prompts.get("pedagogical", {})
        payload = {
            "metadata": lecture.get("metadata", {}),
            "overview": lecture.get("overview", {}),
            "sections": lecture.get("sections", []),
            "problems": lecture.get("problems", []),
            "supplements": lecture.get("supplements", []),
            "summary": lecture.get("summary", []),
        }
        user = str(prompt["user"]).replace("{{LECTURE_JSON}}", json.dumps(payload, ensure_ascii=False, indent=2))
        model = resolve_required_model(config, "pedagogical")
        rid = request_id(workspace_root, config, "review", extra={
            "task_type": "review_pedagogical", "model": model,
            "system": str(prompt["system"]), "user_hash": stable_json_hash(user),
        })
        requests["pedagogical.json"] = {
            "schema_version": "1.1", "request_id": rid, "task_type": "review_pedagogical",
            "required_model": model, "system": str(prompt["system"]), "user": user,
            "packet_provenance": {"source_ids": sorted(valid_target_ids), "frame_ids": []},
            "output_file": "responses/review/pedagogical.json",
        }
        validators["pedagogical.json"] = lambda data: validate_raw_issues(data.get("issues"), review_type="pedagogical", valid_target_ids=valid_target_ids, reject_unreferenced_targets=bool(cfg.get("reject_unreferenced_targets", True)))

    tasks = task_root(workspace_root, "review")
    responses = response_root(workspace_root, "review")
    reusable = {name: (str(req["request_id"]), validators.get(name)) for name, req in requests.items()}
    reused = prepare_task_directories(tasks, responses, reusable=reusable)

    for output_name, request in requests.items():
        write_task_file(tasks / output_name.replace(".json", ".request.json"), request)

    manifest = {
        "schema_version": "1.1",
        "input_id": input_id,
        "request_id": input_id,
        "stage": "review",
        "mode": "codex_handoff",
        "model_routing": resolved_model_routing(config),
        "required_outputs": list(requests.keys()),
        "requests": {
            output: {"request_id": str(req["request_id"]), "request_file": output.replace(".json", ".request.json")}
            for output, req in requests.items()
        },
        "reused_outputs": sorted(reused),
        "valid_target_ids": sorted(valid_target_ids),
    }
    write_task_file(tasks / "manifest.json", manifest)
    record_handoff_prepare(workspace_root, "review", input_id=input_id, requests=requests, reused_outputs=reused, warning_thresholds=config.get("performance", {}).get("packet_warning_chars", {}))

    write_instructions(tasks / "INSTRUCTIONS.md", f"""# Codex Handoff — Review

处理本目录中所有尚未有合法 response 的 `*.request.json`；已有 request_id 完全一致的 response 直接复用。

模型路由：
- factual：`luna-high`
- math：`sol`
- pedagogical：`terra`

职责严格分离：
- factual：只核对是否忠实于视频 Evidence，不判断数学正确性。
- math：只检查数学正确性。`derived_solution` 必须从题目条件独立验算。
- pedagogical：检查结构、图文完整性与独立可读性。

每个响应必须原样回显**该 request 自己的** `request_id`。
math 响应还必须返回 `verified_supplements`，不能用“没有 issue”代替显式确认。

prepare 已复用 {len(reused)} 个合法 reviewer response。
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
    required = list(manifest.get("required_outputs", []))
    responses = response_root(workspace_root, "review")
    all_issues: list[dict[str, Any]] = []
    verified_supplements: set[str] = set()
    for name in required:
        review_type = Path(name).stem
        raw = load_response(responses / name, f"{review_type} review")
        require_request_id(raw, manifest_request_id(manifest, name), f"{review_type} review")
        if review_type == "math":
            values = raw.get("verified_supplements", [])
            if not isinstance(values, list):
                raise StageError("math review.verified_supplements 必须为 list。")
            verified_supplements.update(str(x) for x in values)
        all_issues.extend(validate_raw_issues(
            raw.get("issues"),
            review_type=review_type,
            valid_target_ids=valid,
            reject_unreferenced_targets=bool(cfg.get("reject_unreferenced_targets", True)),
        ))
    issues = assign_issue_ids(all_issues)

    if "math.json" in required:
        math_issues = [x for x in issues if x.get("review_type") == "math"]
        derived_ids = {str(x.get("id", "")) for x in lecture.get("supplements", []) if isinstance(x, dict) and x.get("type") == "derived_solution"}
        unknown_verified = verified_supplements - derived_ids
        if unknown_verified:
            raise StageError("math review 返回未知 supplement id: " + ", ".join(sorted(unknown_verified)))
        for supplement in lecture.get("supplements", []):
            if not isinstance(supplement, dict) or supplement.get("type") != "derived_solution":
                continue
            sid = str(supplement.get("id", ""))
            blockers = [x for x in math_issues if str(x.get("target_id", "")) == sid and str(x.get("severity", "")) in {"warning", "error"}]
            if blockers:
                supplement["math_review_status"] = "rejected"
                supplement["status"] = "uncertain"
            elif sid in verified_supplements:
                supplement["math_review_status"] = "verified"
                supplement["status"] = "confirmed"
            else:
                supplement["math_review_status"] = "pending"
                supplement["status"] = "uncertain"

    lecture.setdefault("review", {})
    lecture["review"]["issues"] = issues
    lecture["review"]["summary"] = {
        "total": len(issues),
        "open": sum(1 for x in issues if x["status"] == "open"),
        "by_type": {t: sum(1 for x in issues if x["review_type"] == t) for t in ("factual", "math", "pedagogical")},
        "by_severity": {s: sum(1 for x in issues if x["severity"] == s) for s in ("info", "warning", "error")},
    }
    lecture.pop("audit", None)
    lecture["stage"] = "review_draft"
    atomic_write_json(lecture_path, lecture)
    out_dir = workspace_root / "review"
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "issues.json", {"schema_version": "1.0", "issues": issues})
    report = {
        "schema_version": "1.0", "stage": "review", "mode": "codex_handoff",
        "issues": lecture["review"]["summary"],
        "verified_derived_solutions": sum(1 for x in lecture.get("supplements", []) if x.get("type") == "derived_solution" and x.get("math_review_status") == "verified"),
        "quality": {
            "complete": all(x.get("math_review_status") == "verified" for x in lecture.get("supplements", []) if isinstance(x, dict) and x.get("type") == "derived_solution")
            and not any(x.get("status") == "open" and (x.get("severity") == "error" or x.get("label") == "possible_teacher_error") for x in issues),
        },
        "output": str(lecture_path),
    }
    atomic_write_json(workspace_root / "reports" / "review_report.json", report)
    record_handoff_apply(workspace_root, "review", responses)
    return report
