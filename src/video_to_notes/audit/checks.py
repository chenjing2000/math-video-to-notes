from __future__ import annotations

from pathlib import Path
from typing import Any


def _issue(
    *,
    category: str,
    code: str,
    severity: str,
    message: str,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "code": code,
        "severity": severity,
        "message": message,
        "target_id": target_id,
        "details": details or {},
    }


def _iter_content_nodes(lecture: dict[str, Any]):
    for section in lecture.get("sections", []):
        yield section
        for block in section.get("blocks", []):
            yield block

    for problem in lecture.get("problems", []):
        yield problem
        for field in (
            "statement",
            "analysis",
            "teacher_solution",
            "supplement_solution",
            "teacher_answer",
        ):
            value = problem.get(field)
            if isinstance(value, dict):
                yield value

    for supplement in lecture.get("supplements", []):
        yield supplement


def audit_evidence(
    lecture: dict[str, Any],
    timeline: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    timeline_items = timeline.get("timeline", [])
    known_evidence = {
        str(item.get("id"))
        for item in timeline_items
        if item.get("id")
    }

    referenced: set[str] = set()
    for node in _iter_content_nodes(lecture):
        for eid in node.get("evidence_ids", []) if isinstance(node, dict) else []:
            referenced.add(str(eid))

    unknown = sorted(referenced - known_evidence)
    for eid in unknown:
        issues.append(_issue(
            category="evidence",
            code="unknown_evidence_id",
            severity="error",
            message=f"lecture.json 引用了不存在的 Evidence ID: {eid}",
            target_id=eid,
        ))

    unresolved_conflicts = [
        item for item in timeline_items
        if str(item.get("status", "")) == "conflict"
    ]
    for item in unresolved_conflicts:
        issues.append(_issue(
            category="evidence",
            code="unresolved_evidence_conflict",
            severity="error",
            message="Evidence Timeline 中仍存在 unresolved conflict。",
            target_id=str(item.get("id")),
        ))

    no_frames = [
        item for item in timeline_items
        if not item.get("frame_ids")
    ]
    for item in no_frames:
        issues.append(_issue(
            category="evidence",
            code="evidence_without_frame",
            severity="warning",
            message="Evidence Segment 没有 publication/evidence frame。",
            target_id=str(item.get("id")),
        ))

    return {
        "name": "evidence",
        "metrics": {
            "timeline_segments": len(timeline_items),
            "known_evidence_ids": len(known_evidence),
            "referenced_evidence_ids": len(referenced),
            "unknown_evidence_ids": len(unknown),
            "unresolved_conflicts": len(unresolved_conflicts),
            "segments_without_frames": len(no_frames),
        },
        "issues": issues,
    }


def audit_content(lecture: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    allowed_origins = {"video", "reconstructed", "supplement"}
    allowed_statuses = {"confirmed", "probable", "uncertain", "conflict"}

    conflicts = 0
    unknown_origins = 0
    unknown_statuses = 0

    for node in _iter_content_nodes(lecture):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "")) or None
        origin = node.get("origin")
        status = node.get("status")

        if origin is not None and str(origin) not in allowed_origins:
            unknown_origins += 1
            issues.append(_issue(
                category="content",
                code="invalid_origin",
                severity="error",
                message=f"非法 content origin: {origin}",
                target_id=node_id,
            ))

        if status is not None and str(status) not in allowed_statuses:
            unknown_statuses += 1
            issues.append(_issue(
                category="content",
                code="invalid_status",
                severity="error",
                message=f"非法 content status: {status}",
                target_id=node_id,
            ))

        if str(status) == "conflict":
            conflicts += 1
            issues.append(_issue(
                category="content",
                code="unresolved_content_conflict",
                severity="error",
                message="课程内容仍标记为 conflict。",
                target_id=node_id,
            ))

    problems = lecture.get("problems", [])
    for problem in problems:
        pid = str(problem.get("id", ""))
        statement = problem.get("statement")
        if not isinstance(statement, dict) or not str(statement.get("content", "")).strip():
            issues.append(_issue(
                category="content",
                code="problem_missing_statement",
                severity="error",
                message="Problem 缺少题目正文。",
                target_id=pid or None,
            ))

        if isinstance(statement, dict) and statement.get("origin") == "video" and not statement.get("evidence_ids"):
            issues.append(_issue(
                category="content",
                code="problem_statement_missing_evidence",
                severity="error",
                message="来自视频的题目正文没有 evidence_ids。",
                target_id=pid or None,
            ))

    return {
        "name": "content",
        "metrics": {
            "sections": len(lecture.get("sections", [])),
            "problems": len(problems),
            "unresolved_conflicts": conflicts,
            "invalid_origins": unknown_origins,
            "invalid_statuses": unknown_statuses,
        },
        "issues": issues,
    }


def audit_supplements(lecture: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    allowed_reasons = {
        "missing_content",
        "incomplete_explanation",
        "unclear_explanation",
        "pedagogical_bridge",
    }

    target_ids: set[str] = set()
    for section in lecture.get("sections", []):
        if section.get("id"):
            target_ids.add(str(section["id"]))
        for block in section.get("blocks", []):
            if block.get("id"):
                target_ids.add(str(block["id"]))
    for problem in lecture.get("problems", []):
        if problem.get("id"):
            target_ids.add(str(problem["id"]))

    supplements = lecture.get("supplements", [])
    for item in supplements:
        sid = str(item.get("id", "")) or None
        target_id = str(item.get("target_id", "")).strip()
        reason = str(item.get("reason", "")).strip()

        if item.get("origin") != "supplement":
            issues.append(_issue(
                category="supplement",
                code="supplement_wrong_origin",
                severity="error",
                message="Supplement 的 origin 必须为 supplement。",
                target_id=sid,
            ))

        if target_id not in target_ids:
            issues.append(_issue(
                category="supplement",
                code="supplement_unknown_target",
                severity="error",
                message=f"Supplement target_id 不存在: {target_id}",
                target_id=sid,
            ))

        if reason not in allowed_reasons:
            issues.append(_issue(
                category="supplement",
                code="supplement_invalid_reason",
                severity="error",
                message=f"Supplement reason 非法: {reason}",
                target_id=sid,
            ))

        if not str(item.get("why_needed", "")).strip():
            issues.append(_issue(
                category="supplement",
                code="supplement_missing_why_needed",
                severity="error",
                message="Supplement 缺少 why_needed。",
                target_id=sid,
            ))

        if not str(item.get("content", "")).strip():
            issues.append(_issue(
                category="supplement",
                code="supplement_empty_content",
                severity="error",
                message="Supplement content 为空。",
                target_id=sid,
            ))

    return {
        "name": "supplement",
        "metrics": {
            "supplements": len(supplements),
        },
        "issues": issues,
    }


def audit_review(
    lecture: dict[str, Any],
    *,
    block_open_possible_teacher_error: bool = True,
    block_open_review_error: bool = True,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    review_issues = lecture.get("review", {}).get("issues", [])

    open_items = [
        item for item in review_issues
        if str(item.get("status", "open")) == "open"
    ]
    possible_teacher_errors = [
        item for item in open_items
        if str(item.get("label", "")) == "possible_teacher_error"
    ]
    open_errors = [
        item for item in open_items
        if str(item.get("severity", "")) == "error"
    ]

    if block_open_possible_teacher_error:
        for item in possible_teacher_errors:
            issues.append(_issue(
                category="review",
                code="open_possible_teacher_error",
                severity="error",
                message="存在尚未处理的 possible_teacher_error。",
                target_id=str(item.get("target_id", "")) or None,
                details={
                    "review_issue_id": item.get("id"),
                    "source_value": item.get("source_value"),
                    "review_value": item.get("review_value"),
                },
            ))

    if block_open_review_error:
        for item in open_errors:
            if item in possible_teacher_errors and block_open_possible_teacher_error:
                continue
            issues.append(_issue(
                category="review",
                code="open_review_error",
                severity="error",
                message="存在尚未处理的 error 级审校问题。",
                target_id=str(item.get("target_id", "")) or None,
                details={"review_issue_id": item.get("id")},
            ))

    return {
        "name": "review",
        "metrics": {
            "issues": len(review_issues),
            "open_issues": len(open_items),
            "open_errors": len(open_errors),
            "open_possible_teacher_errors": len(possible_teacher_errors),
        },
        "issues": issues,
    }


def audit_latex(
    *,
    render_report: dict[str, Any] | None,
    workspace_root: Path,
    required_runs: int = 2,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    tex_path = workspace_root / "latex" / "lecture.tex"
    pdf_path = workspace_root / "output" / "lecture.pdf"

    if not tex_path.exists():
        issues.append(_issue(
            category="latex",
            code="missing_tex",
            severity="error",
            message="缺少 latex/lecture.tex。",
        ))

    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        issues.append(_issue(
            category="latex",
            code="missing_pdf",
            severity="error",
            message="缺少有效 output/lecture.pdf。",
        ))

    metrics = {}
    missing_images: list[str] = []
    runs = 0

    if render_report is None:
        issues.append(_issue(
            category="latex",
            code="missing_render_report",
            severity="error",
            message="缺少 reports/render_report.json。",
        ))
    else:
        metrics = render_report.get("latex_metrics", {}) or {}
        missing_images = list(render_report.get("missing_images", []) or [])
        runs = int(render_report.get("runs", 0) or 0)

        if runs < required_runs:
            issues.append(_issue(
                category="latex",
                code="insufficient_xelatex_runs",
                severity="error",
                message=(
                    f"XeLaTeX 只运行了 {runs} 次，"
                    f"要求至少 {required_runs} 次。"
                ),
            ))

        checks = {
            "latex_errors": "LaTeX Error",
            "undefined_control_sequence": "Undefined control sequence",
            "missing_characters": "Missing character",
        }
        for key, label in checks.items():
            count = int(metrics.get(key, 0) or 0)
            if count > 0:
                issues.append(_issue(
                    category="latex",
                    code=key,
                    severity="error",
                    message=f"{label} 数量为 {count}，要求为 0。",
                ))

        for image in missing_images:
            issues.append(_issue(
                category="latex",
                code="missing_image",
                severity="error",
                message=f"缺失图片: {image}",
            ))

    return {
        "name": "latex",
        "metrics": {
            "tex_exists": tex_path.exists(),
            "pdf_exists": pdf_path.exists() and pdf_path.stat().st_size > 0,
            "xelatex_runs": runs,
            "latex_errors": int(metrics.get("latex_errors", 0) or 0),
            "undefined_control_sequence": int(
                metrics.get("undefined_control_sequence", 0) or 0
            ),
            "missing_characters": int(metrics.get("missing_characters", 0) or 0),
            "overfull_hbox": int(metrics.get("overfull_hbox", 0) or 0),
            "missing_images": len(missing_images),
        },
        "issues": issues,
    }


def audit_figures(lecture: dict[str, Any]) -> dict[str, Any]:
    from ..reconstruction.figures import statement_needs_figure

    issues: list[dict[str, Any]] = []
    figures_by_target: dict[str, list[dict[str, Any]]] = {}
    for figure in lecture.get("figures", []):
        if not isinstance(figure, dict):
            continue
        target_id = str(figure.get("problem_id") or figure.get("target_id") or "").strip()
        if target_id:
            figures_by_target.setdefault(target_id, []).append(figure)

    visual_problems = 0
    missing = 0
    for problem in lecture.get("problems", []):
        if not isinstance(problem, dict):
            continue
        pid = str(problem.get("id", "")).strip()
        if not pid:
            continue
        explicit_ids = problem.get("figure_evidence_ids", [])
        requires_figure = statement_needs_figure(problem) or bool(explicit_ids)
        if not requires_figure:
            continue
        visual_problems += 1
        if not figures_by_target.get(pid):
            missing += 1
            issues.append(_issue(
                category="figure",
                code="problem_missing_required_figure",
                severity="error",
                message="题目依赖图形/已绑定 figure evidence，但最终讲义没有实际插图。",
                target_id=pid,
                details={"figure_evidence_ids": explicit_ids},
            ))

    return {
        "name": "figure",
        "metrics": {
            "figures": len(lecture.get("figures", [])),
            "visual_problems": visual_problems,
            "visual_problems_missing_figure": missing,
        },
        "issues": issues,
    }


def audit_problem_completeness(lecture: dict[str, Any]) -> dict[str, Any]:
    from ..completion.assessment import infer_requires_solution, infer_solution_completeness

    issues: list[dict[str, Any]] = []
    supplements_by_target: dict[str, list[dict[str, Any]]] = {}
    for supplement in lecture.get("supplements", []):
        if not isinstance(supplement, dict):
            continue
        target_id = str(supplement.get("target_id", "")).strip()
        if target_id:
            supplements_by_target.setdefault(target_id, []).append(supplement)

    incomplete = 0
    verified = 0
    for problem in lecture.get("problems", []):
        if not isinstance(problem, dict):
            continue
        pid = str(problem.get("id", "")).strip()
        if not pid or not infer_requires_solution(problem):
            continue

        completeness = infer_solution_completeness(problem)
        needs_completion = completeness in {"incomplete", "missing", "uncertain"}
        if not needs_completion:
            continue
        incomplete += 1

        derived = [
            item for item in supplements_by_target.get(pid, [])
            if item.get("type") == "derived_solution"
        ]
        verified_items = [
            item for item in derived
            if item.get("math_review_status") == "verified"
        ]
        if verified_items:
            verified += 1
            continue

        if not derived:
            issues.append(_issue(
                category="completion",
                code="incomplete_problem_without_derived_solution",
                severity="error",
                message=(
                    f"题目解答状态为 {completeness}，但没有 LLM derived_solution。"
                    "老师没讲完不能作为最终讲义省略证明的理由。"
                ),
                target_id=pid,
            ))
        else:
            issues.append(_issue(
                category="completion",
                code="derived_solution_not_math_verified",
                severity="error",
                message="存在补充推导，但尚未通过 math reviewer 独立验证。",
                target_id=pid,
                details={
                    "derived_solution_ids": [x.get("id") for x in derived],
                    "statuses": [x.get("math_review_status") for x in derived],
                },
            ))

    return {
        "name": "completion",
        "metrics": {
            "incomplete_or_missing_problems": incomplete,
            "verified_completed_problems": verified,
        },
        "issues": issues,
    }
