from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import resolve_resource_path
from ..errors import StageError
from ..reconstruction.prompts import load_prompts
from ..reconstruction.figures import bind_problem_figures
from ..review.evidence_support import collect_evidence_ids_from_targets, select_evidence
from ..review.routing import collect_all_target_ids, collect_factual_targets, collect_math_targets
from ..review.validation import assign_issue_ids, validate_raw_issues
from ..util import atomic_write_json, read_json
from ..receipt import request_id
from .model_routing import resolve_required_model, resolved_model_routing
from .common import ensure_clean_dir, load_response, response_root, task_root, write_instructions, write_task_file, require_request_id


def _project_root(config: dict[str, Any]) -> Path:
    configured = config.get("project", {}).get("project_root")
    return Path(str(configured)).expanduser().resolve() if configured else Path.cwd().resolve()


def prepare_review(*, workspace_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    cfg = config["review"]
    rid = request_id(workspace_root, config, "review")
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

    project_root = _project_root(config)
    prompt_path = resolve_resource_path(cfg.get("prompts_file", "package:prompts.yaml"), default_name="prompts.yaml")
    prompts = load_prompts(prompt_path.resolve()).get("review", {})

    tasks = task_root(workspace_root, "review")
    responses = response_root(workspace_root, "review")
    ensure_clean_dir(tasks)
    ensure_clean_dir(responses)
    required: list[str] = []

    factual_cfg = cfg.get("factual", {})
    if bool(factual_cfg.get("enabled", True)):
        factual_targets = collect_factual_targets(
            lecture,
            trigger_statuses={str(x) for x in factual_cfg.get("trigger_statuses", ["probable", "uncertain", "conflict"])},
            always_review_problem_fields={str(x) for x in factual_cfg.get("always_review_problem_fields", ["statement", "teacher_solution", "teacher_answer"])},
        )
        if factual_targets:
            evidence = select_evidence(timeline, evidence_ids=collect_evidence_ids_from_targets(factual_targets))
            prompt = prompts.get("factual", {})
            user = str(prompt["user"]).replace("{{TARGETS_JSON}}", json.dumps(factual_targets, ensure_ascii=False, indent=2)).replace("{{EVIDENCE_JSON}}", json.dumps(evidence, ensure_ascii=False, indent=2))
            write_task_file(tasks / "factual.request.json", {
                "schema_version": "1.0", "request_id": rid, "task_type": "review_factual",
                "required_model": resolve_required_model(config, "factual"),
                "system": str(prompt["system"]), "user": user,
                "output_file": "responses/review/factual.json",
            })
            required.append("factual.json")

    math_cfg = cfg.get("math", {})
    if bool(math_cfg.get("enabled", True)):
        math_targets = collect_math_targets(lecture, review_all_problems=bool(math_cfg.get("review_all_problems", True)))
        if math_targets:
            prompt = prompts.get("math", {})
            user = str(prompt["user"]).replace("{{TARGETS_JSON}}", json.dumps(math_targets, ensure_ascii=False, indent=2))
            write_task_file(tasks / "math.request.json", {
                "schema_version": "1.0", "request_id": rid, "task_type": "review_math",
                "required_model": resolve_required_model(config, "math"),
                "system": str(prompt["system"]), "user": user,
                "output_file": "responses/review/math.json",
            })
            required.append("math.json")

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
        write_task_file(tasks / "pedagogical.request.json", {
            "schema_version": "1.0", "request_id": rid, "task_type": "review_pedagogical",
            "required_model": resolve_required_model(config, "pedagogical"),
            "system": str(prompt["system"]), "user": user,
            "output_file": "responses/review/pedagogical.json",
        })
        required.append("pedagogical.json")

    manifest = {
        "schema_version": "1.0",
        "request_id": rid,
        "stage": "review",
        "mode": "codex_handoff",
        "model_routing": resolved_model_routing(config),
        "required_outputs": required,
        "valid_target_ids": sorted(collect_all_target_ids(lecture)),
    }
    write_task_file(tasks / "manifest.json", manifest)
    write_instructions(tasks / "INSTRUCTIONS.md", """# Codex Handoff — Review

处理本目录中所有 `*.request.json`，每个任务独立完成，并把纯 JSON 响应写入 `responses/review/` 对应文件。

模型路由：
- factual：`luna-high`（Luna 最低只允许 High）。
- math：`sol`。
- pedagogical：`terra`。

每个 `*.request.json` 都包含 `required_model`；处理该任务前必须使用对应模型。

职责严格分离：
- factual：只核对是否忠实于视频 Evidence，不判断数学正确性。
- math：只检查数学正确性。对 `type=derived_solution` 必须从题目条件独立验算；发现问题时优先把 issue 绑定到具体 supplement id。老师疑似错误必须标记 `possible_teacher_error`，保留 source_value/review_value，不修改原文。
- pedagogical：检查结构、图文完整性与独立可读性；“如图”却无 figure、证明题只有答案无完整解答都应报告。

每个响应必须原样回显 request JSON 中的 `request_id`。
math 响应还必须返回 `verified_supplements`：逐条列出已经独立验算并确认正确的 `derived_solution` supplement id；不能用“没有 issue”代替显式确认。
没有问题时 factual/pedagogical 返回 `{"request_id":"...","issues":[]}`；math 返回 `{"request_id":"...","verified_supplements":[...],"issues":[]}`。
完成后执行 `video-to-notes review apply VIDEO`。
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
        require_request_id(raw, str(manifest.get("request_id", "")), f"{review_type} review")
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

    math_review_ran = "math.json" in required
    if math_review_ran:
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
            and not any(
                x.get("status") == "open"
                and (x.get("severity") == "error" or x.get("label") == "possible_teacher_error")
                for x in issues
            ),
        },
        "output": str(lecture_path),
    }
    atomic_write_json(workspace_root / "reports" / "review_report.json", report)
    return report
