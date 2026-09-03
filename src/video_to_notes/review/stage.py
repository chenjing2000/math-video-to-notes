from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..errors import ModelResponseError
from ..reconstruction.provider import build_provider
from ..stages import StageContext
from .common import (
    empty_math_summary,
    factual_inputs,
    finalize_review,
    load_review_materials,
    render_factual_user,
    render_pedagogical_user,
)
from .evidence_support import collect_evidence_ids_from_targets, select_evidence
from .math_core import (
    apply_math_review_cascade,
    collect_math_review_targets,
    factual_context_for_problem,
    filter_target_for_ids,
    render_math_user,
    resolve_api_llm_config,
    select_math_image_paths,
    unresolved_target_ids,
    validate_math_revision_response,
)
from .pedagogical_core import (
    PEDAGOGICAL_REPAIR_ROUTE,
    apply_repair_round,
    assign_pedagogical_issue_ids,
    build_repair_context,
    group_issues_by_target,
    render_repair_user,
    repair_summary,
    unresolved_pedagogical_issues,
    validate_repair_response,
)
from .validation import validate_raw_issues




def _resolve_repair_api_llm_config(
    pedagogical_cfg: dict[str, Any], logical_model: str
) -> dict[str, Any]:
    """Resolve API transport settings without owning the fixed business route."""
    repair_cfg = pedagogical_cfg.get("repair", {})
    if not isinstance(repair_cfg, dict):
        repair_cfg = {}
    base = repair_cfg.get("llm")
    if not isinstance(base, dict):
        base = pedagogical_cfg.get("llm", {})
    resolved = deepcopy(base) if isinstance(base, dict) else {}
    if str(resolved.get("provider", "openai_compatible")) == "file":
        return resolved
    aliases = repair_cfg.get("api_model_aliases", {})
    alias = aliases.get(logical_model) if isinstance(aliases, dict) else None
    resolved["model"] = str(alias or logical_model)
    return resolved

def _resolve_project_root(ctx: StageContext) -> Path:
    configured = ctx.config.get("project", {}).get("project_root")
    if configured:
        return Path(str(configured)).expanduser().resolve()
    return Path.cwd().resolve()


def run_review_stage(ctx: StageContext) -> None:
    """API transport for the shared review business rules."""
    logger: logging.Logger = ctx.logger
    cfg = ctx.config["review"]
    project_root = _resolve_project_root(ctx)
    lecture_path, lecture, timeline, review_prompts, valid_target_ids, reject_unknown = load_review_materials(
        ctx.workspace_root, ctx.config
    )

    all_issues: list[dict[str, Any]] = []
    run_report: dict[str, Any] = {}

    # 1) Factual review always precedes math review.
    factual_issues: list[dict[str, Any]] = []
    factual_cfg = cfg.get("factual", {})
    if bool(factual_cfg.get("enabled", True)):
        factual_targets, evidence = factual_inputs(lecture, timeline, factual_cfg)
        if factual_targets:
            provider = build_provider(factual_cfg["llm"], project_root=project_root)
            prompt = review_prompts.get("factual", {})
            raw = provider.generate_json(
                system=str(prompt["system"]),
                user=render_factual_user(prompt, factual_targets, evidence),
            )
            factual_issues = validate_raw_issues(
                raw.get("issues"),
                review_type="factual",
                valid_target_ids=valid_target_ids,
                reject_unreferenced_targets=reject_unknown,
            )
            all_issues.extend(factual_issues)
            run_report["factual"] = {
                "triggered": True,
                "targets": len(factual_targets),
                "issues": len(factual_issues),
            }
        else:
            run_report["factual"] = {"triggered": False, "targets": 0, "issues": 0}
    else:
        run_report["factual"] = {"enabled": False}

    # 2) Every problem with any solution process gets one Sol Medium request.
    #    Only unresolved targets from that problem are escalated to Sol High.
    math_cfg = cfg.get("math", {})
    math_targets = collect_math_review_targets(lecture) if bool(math_cfg.get("enabled", True)) else []
    medium_results: dict[str, dict[str, Any]] = {}
    high_results: dict[str, dict[str, Any]] = {}
    escalated_problem_count = 0
    math_summary = empty_math_summary()

    if math_targets:
        primary_model = str(math_cfg.get("primary_model", "sol-medium"))
        high_model = str(math_cfg.get("escalation_model", "sol-high"))
        primary_provider = build_provider(
            resolve_api_llm_config(math_cfg, primary_model), project_root=project_root
        )
        high_provider = None
        max_images = int(math_cfg.get("max_images_per_problem", 2))

        for target in math_targets:
            pid = str(target.get("target_id", ""))
            evidence_ids = collect_evidence_ids_from_targets([target])
            evidence = select_evidence(timeline, evidence_ids=evidence_ids)
            factual_context = factual_context_for_problem(factual_issues, pid)
            images = select_math_image_paths(
                lecture,
                target,
                timeline,
                workspace_root=ctx.workspace_root,
                max_images=max_images,
            )
            prompt = review_prompts.get("math", {})
            user = render_math_user(
                prompt,
                target,
                evidence=evidence,
                factual_issues=factual_context,
                image_paths=images,
            )
            raw = primary_provider.generate_json(
                system=str(prompt["system"]), user=user, image_paths=[Path(x) for x in images]
            )
            medium = validate_math_revision_response(raw, [target])
            medium_results[pid] = medium
            unresolved = unresolved_target_ids(medium)
            if unresolved:
                escalated_problem_count += 1
                if high_provider is None:
                    high_provider = build_provider(
                        resolve_api_llm_config(math_cfg, high_model), project_root=project_root
                    )
                high_target = filter_target_for_ids(target, unresolved)
                high_prompt = review_prompts.get("math_high", {})
                high_user = render_math_user(
                    high_prompt,
                    high_target,
                    evidence=evidence,
                    factual_issues=factual_context,
                    image_paths=images,
                )
                high_raw = high_provider.generate_json(
                    system=str(high_prompt["system"]),
                    user=high_user,
                    image_paths=[Path(x) for x in images],
                )
                high_results[pid] = validate_math_revision_response(high_raw, [high_target])

        math_summary = apply_math_review_cascade(
            lecture, math_targets, medium_results=medium_results, high_results=high_results
        )
        run_report["math"] = {
            "triggered": True,
            "problems": len(math_targets),
            "medium_requests": len(math_targets),
            "high_escalations": escalated_problem_count,
            "high_escalation_rate": round(escalated_problem_count / len(math_targets), 4),
            "verified": math_summary["verified"],
            "revised": math_summary["revised"],
            "unresolved": math_summary["unresolved"],
        }
    else:
        run_report["math"] = {"triggered": False, "problems": 0}

    # 3) Pedagogical review sees the publication-oriented math view.
    pedagogical_cfg = cfg.get("pedagogical", {})
    pedagogical_issues: list[dict[str, Any]] = []
    pedagogical_repair_report = repair_summary([], [])
    if bool(pedagogical_cfg.get("enabled", True)) and bool(pedagogical_cfg.get("whole_lecture", True)):
        provider = build_provider(pedagogical_cfg["llm"], project_root=project_root)
        prompt = review_prompts.get("pedagogical", {})
        user = render_pedagogical_user(prompt, lecture)
        raw = provider.generate_json(system=str(prompt["system"]), user=user)
        pedagogical_issues = assign_pedagogical_issue_ids(validate_raw_issues(
            raw.get("issues"),
            review_type="pedagogical",
            valid_target_ids=valid_target_ids,
            reject_unreferenced_targets=reject_unknown,
        ))
        run_report["pedagogical"] = {"triggered": True, "issues": len(pedagogical_issues)}

        repair_cfg = pedagogical_cfg.get("repair", {})
        repair_enabled = bool(repair_cfg.get("enabled", True)) if isinstance(repair_cfg, dict) else True
        repair_round_reports: list[dict[str, Any]] = []
        if pedagogical_issues and repair_enabled:
            repair_prompt = review_prompts.get("pedagogical_repair", {})
            file_provider = None
            explicit_repair_llm = repair_cfg.get("llm") if isinstance(repair_cfg, dict) else None
            base_repair_llm = explicit_repair_llm if isinstance(explicit_repair_llm, dict) else None
            pedagogical_llm = pedagogical_cfg.get("llm", {})
            pedagogical_provider = (
                str(pedagogical_llm.get("provider", ""))
                if isinstance(pedagogical_llm, dict)
                else ""
            )
            # FileProvider is mainly a deterministic test/offline transport.  A legacy
            # config normally contains only one pedagogical response file, so do not
            # accidentally consume that same response as a repair payload.  File-mode
            # repairs therefore require an explicit pedagogical.repair.llm block.
            if isinstance(base_repair_llm, dict) and str(base_repair_llm.get("provider", "")) == "file":
                file_provider = build_provider(base_repair_llm, project_root=project_root)
            can_run_repair = not (pedagogical_provider == "file" and base_repair_llm is None)

            for round_index, model in enumerate(PEDAGOGICAL_REPAIR_ROUTE, start=1):
                if not can_run_repair:
                    break
                pending = unresolved_pedagogical_issues(pedagogical_issues)
                if not pending:
                    break
                groups = group_issues_by_target(pending)
                round_repairs: list[dict[str, Any]] = []
                if file_provider is not None:
                    repair_provider = file_provider
                else:
                    repair_provider = build_provider(
                        _resolve_repair_api_llm_config(pedagogical_cfg, model),
                        project_root=project_root,
                    )
                invalid_issue_ids: list[str] = []
                for target_id, target_issues in groups.items():
                    repair_user = render_repair_user(
                        repair_prompt,
                        round_index=round_index,
                        model=model,
                        target_context=build_repair_context(lecture, target_id),
                        issues=target_issues,
                    )
                    try:
                        repair_raw = repair_provider.generate_json(
                            system=str(repair_prompt["system"]), user=repair_user
                        )
                        round_repairs.extend(validate_repair_response(
                            repair_raw, expected_issues=target_issues
                        ))
                    except ModelResponseError:
                        # A response existed but was unusable.  It consumes this business
                        # round for the affected issues; transport failures still propagate.
                        invalid_issue_ids.extend(
                            str(issue.get("pedagogical_issue_id", ""))
                            for issue in target_issues
                            if str(issue.get("pedagogical_issue_id", ""))
                        )
                repair_round_reports.append(apply_repair_round(
                    lecture,
                    pedagogical_issues,
                    round_repairs,
                    round_index=round_index,
                    model=model,
                    invalid_issue_ids=invalid_issue_ids,
                ))

        pedagogical_repair_report = repair_summary(
            pedagogical_issues, repair_round_reports
        )
        all_issues.extend(pedagogical_issues)
        run_report["pedagogical"]["repair"] = pedagogical_repair_report
    else:
        run_report["pedagogical"] = {"triggered": False, "issues": 0}

    report = finalize_review(
        workspace_root=ctx.workspace_root,
        lecture_path=lecture_path,
        lecture=lecture,
        raw_issues=all_issues,
        math_summary=math_summary,
        mode="api",
        reviewers=run_report,
        pedagogical_repair=pedagogical_repair_report,
    )
    logger.info(
        "[review] issues=%d math_problems=%d high_escalations=%d unresolved=%d",
        int(report["issues"].get("total", 0)),
        len(math_targets),
        escalated_problem_count,
        int(math_summary.get("unresolved", 0)),
    )
