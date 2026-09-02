from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..config import resolve_resource_path
from ..errors import StageError
from ..reconstruction.prompts import load_prompts, render
from ..reconstruction.provider import build_provider
from ..stages import StageContext
from ..util import atomic_write_json, read_json
from .evidence_support import (
    collect_evidence_ids_from_targets,
    select_evidence,
)
from .routing import (
    collect_all_target_ids,
    collect_factual_targets,
    collect_math_targets,
)
from .validation import assign_issue_ids, validate_raw_issues


def _resolve_project_root(ctx: StageContext) -> Path:
    configured = ctx.config.get("project", {}).get("project_root")
    if configured:
        return Path(str(configured)).expanduser().resolve()
    return Path.cwd().resolve()


def _load_json(path: Path, description: str) -> dict[str, Any]:
    if not path.exists():
        raise StageError(f"缺少 {description}: {path}")
    data = read_json(path)
    if not isinstance(data, dict):
        raise StageError(f"{description} 根节点必须为 object。")
    return data


def _run_reviewer(
    *,
    review_type: str,
    provider,
    prompt: dict[str, Any],
    placeholder: str,
    payload: Any,
    valid_target_ids: set[str],
    reject_unreferenced_targets: bool,
) -> list[dict[str, Any]]:
    user = render(
        str(prompt["user"]),
        placeholder,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    result = provider.generate_json(
        system=str(prompt["system"]),
        user=user,
    )
    return validate_raw_issues(
        result.get("issues"),
        review_type=review_type,
        valid_target_ids=valid_target_ids,
        reject_unreferenced_targets=reject_unreferenced_targets,
    )


def run_review_stage(ctx: StageContext) -> None:
    logger: logging.Logger = ctx.logger
    cfg = ctx.config["review"]
    project_root = _resolve_project_root(ctx)

    lecture_path = ctx.workspace_root / "lecture" / "lecture.json"
    lecture = _load_json(lecture_path, "lecture.json")
    if str(lecture.get("stage", "")) not in {
        "completion_draft",
        "review_draft",
    }:
        raise StageError(
            "review stage 只接受 completion_draft/review_draft。"
        )

    timeline_data = _load_json(
        ctx.workspace_root / "evidence" / "timeline.json",
        "Evidence Timeline",
    )
    timeline = timeline_data.get("timeline")
    if not isinstance(timeline, list):
        raise StageError("Evidence Timeline.timeline 必须为 list。")

    prompt_path = resolve_resource_path(cfg.get("prompts_file", "package:prompts.yaml"), default_name="prompts.yaml")
    prompts = load_prompts(prompt_path.resolve())
    review_prompts = prompts.get("review", {})
    if not isinstance(review_prompts, dict):
        raise StageError("prompts.yaml 缺少 review。")

    valid_target_ids = collect_all_target_ids(lecture)
    reject_unknown = bool(cfg.get("reject_unreferenced_targets", True))
    all_issues: list[dict[str, Any]] = []
    run_report: dict[str, Any] = {}
    verified_supplements: set[str] = set()

    # Factual reviewer: important problem fields + low-confidence content.
    factual_cfg = cfg.get("factual", {})
    if bool(factual_cfg.get("enabled", True)):
        factual_targets = collect_factual_targets(
            lecture,
            trigger_statuses={
                str(x)
                for x in factual_cfg.get(
                    "trigger_statuses",
                    ["probable", "uncertain", "conflict"],
                )
            },
            always_review_problem_fields={
                str(x)
                for x in factual_cfg.get(
                    "always_review_problem_fields",
                    ["statement", "teacher_solution", "teacher_answer"],
                )
            },
        )

        if factual_targets:
            evidence_ids = collect_evidence_ids_from_targets(factual_targets)
            factual_evidence = select_evidence(
                timeline,
                evidence_ids=evidence_ids,
            )
            provider = build_provider(
                factual_cfg["llm"],
                project_root=project_root,
            )

            factual_prompt = review_prompts.get("factual", {})
            user_payload = {
                "targets": factual_targets,
                "evidence": factual_evidence,
            }
            # Use two replacements because render handles one placeholder.
            user = str(factual_prompt["user"])
            user = user.replace(
                "{{TARGETS_JSON}}",
                json.dumps(
                    factual_targets,
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            user = user.replace(
                "{{EVIDENCE_JSON}}",
                json.dumps(
                    factual_evidence,
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            result = provider.generate_json(
                system=str(factual_prompt["system"]),
                user=user,
            )
            issues = validate_raw_issues(
                result.get("issues"),
                review_type="factual",
                valid_target_ids=valid_target_ids,
                reject_unreferenced_targets=reject_unknown,
            )
            all_issues.extend(issues)
            run_report["factual"] = {
                "triggered": True,
                "targets": len(factual_targets),
                "evidence_segments": len(factual_evidence),
                "issues": len(issues),
            }
        else:
            run_report["factual"] = {
                "triggered": False,
                "targets": 0,
                "evidence_segments": 0,
                "issues": 0,
            }
    else:
        run_report["factual"] = {"enabled": False}

    # Math reviewer: mathematics/problem content only.
    math_cfg = cfg.get("math", {})
    if bool(math_cfg.get("enabled", True)):
        math_targets = collect_math_targets(
            lecture,
            review_all_problems=bool(
                math_cfg.get("review_all_problems", True)
            ),
        )
        if math_targets:
            provider = build_provider(
                math_cfg["llm"],
                project_root=project_root,
            )
            prompt = review_prompts.get("math", {})
            user = render(str(prompt["user"]), "TARGETS_JSON", json.dumps(math_targets, ensure_ascii=False, indent=2))
            result = provider.generate_json(system=str(prompt["system"]), user=user)
            values = result.get("verified_supplements", [])
            if not isinstance(values, list):
                raise StageError("math review.verified_supplements 必须为 list。")
            verified_supplements.update(str(x) for x in values)
            issues = validate_raw_issues(
                result.get("issues"), review_type="math", valid_target_ids=valid_target_ids,
                reject_unreferenced_targets=reject_unknown,
            )
            all_issues.extend(issues)
            run_report["math"] = {
                "triggered": True,
                "targets": len(math_targets),
                "issues": len(issues),
            }
        else:
            run_report["math"] = {
                "triggered": False,
                "targets": 0,
                "issues": 0,
            }
    else:
        run_report["math"] = {"enabled": False}

    # Pedagogical reviewer: one global pass, if enabled.
    pedagogical_cfg = cfg.get("pedagogical", {})
    if (
        bool(pedagogical_cfg.get("enabled", True))
        and bool(pedagogical_cfg.get("whole_lecture", True))
    ):
        provider = build_provider(
            pedagogical_cfg["llm"],
            project_root=project_root,
        )
        prompt = review_prompts.get("pedagogical", {})
        pedagogical_payload = {
            "metadata": lecture.get("metadata", {}),
            "overview": lecture.get("overview", {}),
            "sections": lecture.get("sections", []),
            "problems": lecture.get("problems", []),
            "supplements": lecture.get("supplements", []),
            "summary": lecture.get("summary", []),
        }
        issues = _run_reviewer(
            review_type="pedagogical",
            provider=provider,
            prompt=prompt,
            placeholder="LECTURE_JSON",
            payload=pedagogical_payload,
            valid_target_ids=valid_target_ids,
            reject_unreferenced_targets=reject_unknown,
        )
        all_issues.extend(issues)
        run_report["pedagogical"] = {
            "triggered": True,
            "issues": len(issues),
        }
    else:
        run_report["pedagogical"] = {
            "triggered": False,
            "issues": 0,
        }

    issues = assign_issue_ids(all_issues)

    math_review_ran = bool(run_report.get("math", {}).get("triggered", False))
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
        "by_type": {
            review_type: sum(
                1 for x in issues if x["review_type"] == review_type
            )
            for review_type in ("factual", "math", "pedagogical")
        },
        "by_severity": {
            severity: sum(
                1 for x in issues if x["severity"] == severity
            )
            for severity in ("info", "warning", "error")
        },
    }
    lecture.pop("audit", None)
    lecture["stage"] = "review_draft"

    atomic_write_json(lecture_path, lecture)

    review_dir = ctx.workspace_root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        review_dir / "issues.json",
        {
            "schema_version": "1.0",
            "issues": issues,
        },
    )

    report = {
        "schema_version": "1.0",
        "stage": "review",
        "reviewers": run_report,
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
    atomic_write_json(
        ctx.workspace_root / "reports" / "review_report.json",
        report,
    )

    logger.info(
        "[review] issues=%d factual=%d math=%d pedagogical=%d",
        len(issues),
        lecture["review"]["summary"]["by_type"]["factual"],
        lecture["review"]["summary"]["by_type"]["math"],
        lecture["review"]["summary"]["by_type"]["pedagogical"],
    )
