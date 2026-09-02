from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import resolve_resource_path
from ..errors import StageError
from ..reconstruction.figures import bind_problem_figures
from ..reconstruction.prompts import load_prompts
from ..util import atomic_write_json, read_json
from .evidence_support import collect_evidence_ids_from_targets, select_evidence
from .routing import collect_all_target_ids, collect_factual_targets
from .validation import assign_issue_ids


def load_review_materials(
    workspace_root: Path,
    config: dict[str, Any],
    *,
    allowed_stages: set[str] | None = None,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]], dict[str, Any], set[str], bool]:
    """Load and validate the shared inputs used by both Codex and API review paths."""
    lecture_path = workspace_root / "lecture" / "lecture.json"
    timeline_path = workspace_root / "evidence" / "timeline.json"
    if not lecture_path.exists():
        raise StageError(f"缺少 lecture.json: {lecture_path}")
    if not timeline_path.exists():
        raise StageError(f"缺少 Evidence Timeline: {timeline_path}")

    lecture = read_json(lecture_path)
    if not isinstance(lecture, dict):
        raise StageError("lecture.json 根节点必须为 object。")
    allowed = allowed_stages or {"completion_draft", "review_draft"}
    if str(lecture.get("stage", "")) not in allowed:
        names = "/".join(sorted(allowed))
        raise StageError(f"review stage 只接受 {names}。")

    timeline_data = read_json(timeline_path)
    if not isinstance(timeline_data, dict):
        raise StageError("Evidence Timeline 根节点必须为 object。")
    timeline = timeline_data.get("timeline")
    if not isinstance(timeline, list):
        raise StageError("Evidence Timeline.timeline 必须为 list。")

    bind_problem_figures(
        lecture,
        timeline,
        workspace_root=workspace_root,
        infer_from_statement=bool(config.get("reconstruction", {}).get("infer_problem_figures", True)),
        max_figures_per_problem=int(config.get("reconstruction", {}).get("max_figures_per_problem", 2)),
    )

    cfg = config["review"]
    prompt_path = resolve_resource_path(
        cfg.get("prompts_file", "package:prompts.yaml"), default_name="prompts.yaml"
    )
    prompts = load_prompts(prompt_path.resolve()).get("review", {})
    if not isinstance(prompts, dict):
        raise StageError("prompts.yaml 缺少 review。")

    valid_target_ids = collect_all_target_ids(lecture)
    reject_unknown = bool(cfg.get("reject_unreferenced_targets", True))
    return lecture_path, lecture, timeline, prompts, valid_target_ids, reject_unknown


def factual_inputs(
    lecture: dict[str, Any],
    timeline: list[dict[str, Any]],
    factual_cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    targets = collect_factual_targets(
        lecture,
        trigger_statuses={
            str(x)
            for x in factual_cfg.get("trigger_statuses", ["probable", "uncertain", "conflict"])
        },
        always_review_problem_fields={
            str(x)
            for x in factual_cfg.get(
                "always_review_problem_fields", ["statement", "teacher_solution", "teacher_answer"]
            )
        },
    )
    evidence_ids = collect_evidence_ids_from_targets(targets)
    return targets, select_evidence(timeline, evidence_ids=evidence_ids)


def render_factual_user(
    prompt: dict[str, Any],
    targets: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> str:
    user = str(prompt["user"])
    user = user.replace("{{TARGETS_JSON}}", json.dumps(targets, ensure_ascii=False, indent=2))
    return user.replace("{{EVIDENCE_JSON}}", json.dumps(evidence, ensure_ascii=False, indent=2))


def pedagogical_payload(lecture: dict[str, Any]) -> dict[str, Any]:
    return {
        "metadata": lecture.get("metadata", {}),
        "overview": lecture.get("overview", {}),
        "sections": lecture.get("sections", []),
        "problems": lecture.get("problems", []),
        "supplements": lecture.get("supplements", []),
        "summary": lecture.get("summary", []),
    }


def render_pedagogical_user(prompt: dict[str, Any], lecture: dict[str, Any]) -> str:
    return str(prompt["user"]).replace(
        "{{LECTURE_JSON}}", json.dumps(pedagogical_payload(lecture), ensure_ascii=False, indent=2)
    )


def empty_math_summary() -> dict[str, Any]:
    return {
        "reviewed_targets": [],
        "resolved_targets": [],
        "escalated_targets": [],
        "unresolved_targets": [],
        "problems_with_unresolved": [],
        "verified": 0,
        "revised": 0,
        "unresolved": 0,
        "complete": True,
        "complete_with_unresolved": False,
    }


def finalize_review(
    *,
    workspace_root: Path,
    lecture_path: Path,
    lecture: dict[str, Any],
    raw_issues: list[dict[str, Any]],
    math_summary: dict[str, Any],
    mode: str,
    reviewers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply the single authoritative review finalization contract."""
    issues = assign_issue_ids(raw_issues)
    resolved_targets = set(math_summary.get("resolved_targets", []))
    for issue in issues:
        if (
            issue.get("review_type") == "factual"
            and issue.get("target_id") in resolved_targets
            and issue.get("status") == "open"
        ):
            issue["status"] = "accepted_review"

    summary = {
        "total": len(issues),
        "open": sum(1 for x in issues if x["status"] == "open"),
        "by_type": {
            kind: sum(1 for x in issues if x["review_type"] == kind)
            for kind in ("factual", "math", "pedagogical")
        },
        "by_severity": {
            severity: sum(1 for x in issues if x["severity"] == severity)
            for severity in ("info", "warning", "error")
        },
    }
    lecture.setdefault("review", {})
    lecture["review"]["issues"] = issues
    lecture["review"]["math"] = math_summary
    lecture["review"]["summary"] = summary
    lecture.pop("audit", None)
    lecture["stage"] = "review_draft"
    atomic_write_json(lecture_path, lecture)

    review_dir = workspace_root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(review_dir / "issues.json", {"schema_version": "1.3", "issues": issues})

    blocking_issue = any(
        issue.get("status") == "open"
        and (issue.get("severity") == "error" or issue.get("label") == "possible_teacher_error")
        for issue in issues
    )
    notes: list[dict[str, Any]] = []
    if math_summary.get("complete_with_unresolved"):
        notes.append(
            {
                "type": "math_unresolved",
                "problems": math_summary.get("problems_with_unresolved", []),
                "message": "Sol High 仍有未解决数学 target；PDF 将保留既有内容并标注未处理完成。",
            }
        )

    report: dict[str, Any] = {
        "schema_version": "1.3",
        "stage": "review",
        "mode": mode,
        "issues": summary,
        "math_review": math_summary,
        "quality": {
            "complete": not blocking_issue,
            "has_notes": bool(notes),
            "notes": notes,
        },
        "output": str(lecture_path),
    }
    if reviewers is not None:
        report["reviewers"] = reviewers
    atomic_write_json(workspace_root / "reports" / "review_report.json", report)
    return report
