from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ..errors import ModelResponseError, StageError

# Pedagogical repair is deliberately a fixed three-round business policy.  API and
# Codex transports both consume this same route; provider-specific model aliases live
# outside this core module.
PEDAGOGICAL_REPAIR_ROUTE = ("terra-xhigh", "sol-medium", "sol-high")
# Backward-compatible public name used by v1.2.5 callers/tests.
PEDAGOGICAL_REPAIR_MODELS = PEDAGOGICAL_REPAIR_ROUTE

REPAIR_RESOLVED = "resolved"
REPAIR_UNRESOLVED_NON_BLOCKING = "unresolved_non_blocking"
REPAIR_INVALID = "invalid"

ALLOWED_REPAIR_STATUS = {"resolved", "unresolved"}
ALLOWED_REPAIR_ACTIONS = {
    "keep",
    "replace_target",
    "append_supplement",
    "append_summary",
    "remove_target",
}


def repair_model(round_index: int) -> str | None:
    """Return the logical model for a 1-based repair round, or None after round 3."""
    if 1 <= round_index <= len(PEDAGOGICAL_REPAIR_ROUTE):
        return PEDAGOGICAL_REPAIR_ROUTE[round_index - 1]
    return None


def next_repair_model(round_index: int, business_status: str) -> str | None:
    """Return the next logical model unless the current business result is resolved."""
    if business_status == REPAIR_RESOLVED:
        return None
    return repair_model(round_index + 1)


def assign_pedagogical_issue_ids(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give pedagogical issues stable local IDs for the repair loop."""
    out: list[dict[str, Any]] = []
    for index, issue in enumerate(issues, start=1):
        item = deepcopy(issue)
        item["pedagogical_issue_id"] = f"pg_{index:03d}"
        out.append(item)
    return out


def unresolved_pedagogical_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in issues
        if isinstance(issue, dict) and str(issue.get("status", "open")) != "resolved"
    ]


def group_issues_by_target(issues: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        target_id = str(issue.get("target_id", "")).strip()
        if target_id:
            grouped.setdefault(target_id, []).append(issue)
    return grouped


def _problem_id_for_target(lecture: dict[str, Any], target_id: str) -> str | None:
    for problem in lecture.get("problems", []):
        if not isinstance(problem, dict):
            continue
        pid = str(problem.get("id", "")).strip()
        if not pid:
            continue
        if target_id == pid or target_id.startswith(pid + "."):
            return pid
    for supplement in lecture.get("supplements", []):
        if not isinstance(supplement, dict):
            continue
        if str(supplement.get("id", "")).strip() == target_id:
            sid = str(supplement.get("target_id", "")).strip()
            if sid:
                for problem in lecture.get("problems", []):
                    if isinstance(problem, dict) and str(problem.get("id", "")).strip() == sid:
                        return sid
    return None


def build_repair_context(lecture: dict[str, Any], target_id: str) -> dict[str, Any]:
    """Return local context, including the full current problem for problem targets."""
    pid = _problem_id_for_target(lecture, target_id)
    if pid:
        problem = next(
            deepcopy(problem)
            for problem in lecture.get("problems", [])
            if isinstance(problem, dict) and str(problem.get("id", "")).strip() == pid
        )
        section_id = str(problem.get("section_id", "")).strip()
        section = next(
            (
                deepcopy(section)
                for section in lecture.get("sections", [])
                if isinstance(section, dict) and str(section.get("id", "")).strip() == section_id
            ),
            None,
        )
        supplements = [
            deepcopy(item)
            for item in lecture.get("supplements", [])
            if isinstance(item, dict) and str(item.get("target_id", "")).strip() in {pid, target_id}
        ]
        return {
            "target_id": target_id,
            "problem": problem,
            "section": section,
            "supplements": supplements,
        }

    for section in lecture.get("sections", []):
        if not isinstance(section, dict):
            continue
        sid = str(section.get("id", "")).strip()
        block_ids = {
            str(block.get("id", "")).strip()
            for block in section.get("blocks", [])
            if isinstance(block, dict) and block.get("id")
        }
        if target_id == sid or target_id in block_ids:
            problems = [
                deepcopy(problem)
                for problem in lecture.get("problems", [])
                if isinstance(problem, dict) and str(problem.get("section_id", "")).strip() == sid
            ]
            supplements = [
                deepcopy(item)
                for item in lecture.get("supplements", [])
                if isinstance(item, dict) and str(item.get("target_id", "")).strip() in {sid, target_id}
            ]
            return {
                "target_id": target_id,
                "section": deepcopy(section),
                "problems": problems,
                "supplements": supplements,
            }

    if target_id == "lecture":
        return {
            "target_id": target_id,
            "metadata": deepcopy(lecture.get("metadata", {})),
            "overview": deepcopy(lecture.get("overview", {})),
            "sections": deepcopy(lecture.get("sections", [])),
            "problems": deepcopy(lecture.get("problems", [])),
            "supplements": deepcopy(lecture.get("supplements", [])),
            "summary": deepcopy(lecture.get("summary", [])),
        }

    for supplement in lecture.get("supplements", []):
        if isinstance(supplement, dict) and str(supplement.get("id", "")).strip() == target_id:
            return {"target_id": target_id, "supplement": deepcopy(supplement)}

    return {"target_id": target_id}


def validate_repair_response(
    data: dict[str, Any],
    *,
    expected_issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate one model repair payload without mutating lecture state."""
    raw = data.get("repairs")
    if not isinstance(raw, list):
        raise ModelResponseError("pedagogical repair.repairs 必须为 list。")

    expected = {
        str(issue.get("pedagogical_issue_id", "")): str(issue.get("target_id", ""))
        for issue in expected_issues
        if isinstance(issue, dict)
    }
    if not expected or any(not key or not value for key, value in expected.items()):
        raise StageError("pedagogical repair 缺少稳定 issue_id/target_id。")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ModelResponseError(f"pedagogical repair.repairs[{index}] 必须为 object。")
        issue_id = str(item.get("issue_id", "")).strip()
        target_id = str(item.get("target_id", "")).strip()
        claimed_status = str(item.get("status", "")).strip()
        action = str(item.get("action", "keep")).strip() or "keep"
        content = str(item.get("content", "")).strip()

        if issue_id not in expected:
            raise ModelResponseError(f"pedagogical repair 返回未知 issue_id: {issue_id!r}")
        if issue_id in seen:
            raise ModelResponseError(f"pedagogical repair 重复 issue_id: {issue_id}")
        if target_id != expected[issue_id]:
            raise ModelResponseError(
                f"pedagogical repair {issue_id} target_id 不匹配: {target_id!r} != {expected[issue_id]!r}"
            )
        if claimed_status not in ALLOWED_REPAIR_STATUS:
            raise ModelResponseError(
                f"pedagogical repair {issue_id} status 非法: {claimed_status!r}"
            )
        if action not in ALLOWED_REPAIR_ACTIONS:
            raise ModelResponseError(f"pedagogical repair {issue_id} action 非法: {action!r}")

        if claimed_status == "unresolved":
            action = "keep"
            content = ""
        elif action in {"replace_target", "append_supplement", "append_summary"} and not content:
            raise ModelResponseError(
                f"pedagogical repair {issue_id} action={action} 时 content 不能为空。"
            )
        elif action == "remove_target":
            content = ""

        normalized.append(
            {
                "issue_id": issue_id,
                "target_id": target_id,
                "claimed_status": claimed_status,
                # Keep the legacy key for compatibility with existing fixtures/callers.
                "status": claimed_status,
                "action": action,
                "content": content,
            }
        )
        seen.add(issue_id)

    missing = set(expected) - seen
    if missing:
        raise ModelResponseError(
            "pedagogical repair 漏处理 issue_id: " + ", ".join(sorted(missing))
        )
    return normalized


def render_repair_user(
    prompt: dict[str, Any],
    *,
    round_index: int,
    model: str,
    target_context: dict[str, Any],
    issues: list[dict[str, Any]],
) -> str:
    user = str(prompt.get("user", ""))
    user = user.replace("{{ROUND}}", str(round_index))
    user = user.replace("{{MODEL}}", model)
    user = user.replace(
        "{{TARGET_CONTEXT_JSON}}", json.dumps(target_context, ensure_ascii=False, indent=2)
    )
    return user.replace("{{ISSUES_JSON}}", json.dumps(issues, ensure_ascii=False, indent=2))


def _find_problem(lecture: dict[str, Any], problem_id: str) -> dict[str, Any] | None:
    for problem in lecture.get("problems", []):
        if isinstance(problem, dict) and str(problem.get("id", "")).strip() == problem_id:
            return problem
    return None


def _replace_target(lecture: dict[str, Any], target_id: str, content: str, *, model: str) -> bool:
    for section in lecture.get("sections", []):
        if not isinstance(section, dict):
            continue
        for block in section.get("blocks", []):
            if isinstance(block, dict) and str(block.get("id", "")).strip() == target_id:
                block["content"] = content
                block["pedagogical_repair_model"] = model
                return True

    for supplement in lecture.get("supplements", []):
        if isinstance(supplement, dict) and str(supplement.get("id", "")).strip() == target_id:
            supplement["content"] = content
            supplement["pedagogical_repair_model"] = model
            return True

    pid = _problem_id_for_target(lecture, target_id)
    if not pid:
        return False
    problem = _find_problem(lecture, pid)
    if problem is None:
        return False

    if target_id.endswith(".analysis"):
        current = problem.get("analysis")
        if not isinstance(current, dict):
            current = {"origin": "pedagogical_repair", "status": "confirmed", "evidence_ids": []}
            problem["analysis"] = current
        current["content"] = content
        current["pedagogical_repair_model"] = model
        return True

    if target_id.endswith(".supplement_solution"):
        current = problem.get("supplement_solution")
        if not isinstance(current, dict):
            current = {"origin": "supplement", "status": "confirmed", "evidence_ids": []}
            problem["supplement_solution"] = current
        current["content"] = content
        current["pedagogical_repair_model"] = model
        return True

    # Teacher source remains immutable.  A rewrite of a source-facing target is stored
    # only in its publication-layer counterpart.
    if target_id == pid or target_id.endswith(".teacher_solution"):
        publication = problem.get("publication_solution")
        if isinstance(publication, dict):
            publication["content"] = content
            publication["pedagogical_repair_model"] = model
            publication["pedagogical_repaired"] = True
            return True
        return False

    if target_id.endswith(".teacher_answer"):
        publication = problem.get("publication_answer")
        if isinstance(publication, dict):
            publication["content"] = content
            publication["pedagogical_repair_model"] = model
            publication["pedagogical_repaired"] = True
            return True
        return False

    return False


def _append_supplement(
    lecture: dict[str, Any],
    target_id: str,
    content: str,
    *,
    issue_id: str,
    model: str,
) -> bool:
    sid = f"sup_{issue_id}"
    for supplement in lecture.get("supplements", []):
        if isinstance(supplement, dict) and str(supplement.get("id", "")) == sid:
            supplement["content"] = content
            supplement["pedagogical_repair_model"] = model
            return True

    problem_id = _problem_id_for_target(lecture, target_id)
    attachment = problem_id or target_id
    lecture.setdefault("supplements", []).append(
        {
            "id": sid,
            "target_id": attachment,
            "reason": "pedagogical_bridge",
            "type": "explanation",
            "why_needed": "Pedagogical Review 局部修复。",
            "content": content,
            "origin": "pedagogical_repair",
            "status": "confirmed",
            "pedagogical_repair_model": model,
        }
    )
    return True


def _append_summary(
    lecture: dict[str, Any],
    content: str,
    *,
    issue_id: str,
    model: str,
) -> bool:
    summary = lecture.setdefault("summary", [])
    sid = f"summary_{issue_id}"
    for item in summary:
        if isinstance(item, dict) and str(item.get("id", "")) == sid:
            item["content"] = content
            item["pedagogical_repair_model"] = model
            return True
    summary.append(
        {
            "id": sid,
            "content": content,
            "origin": "pedagogical_repair",
            "status": "confirmed",
            "pedagogical_repair_model": model,
        }
    )
    return True


def _remove_target(lecture: dict[str, Any], target_id: str) -> bool:
    supplements = lecture.get("supplements", [])
    if isinstance(supplements, list):
        kept = [
            item
            for item in supplements
            if not (isinstance(item, dict) and str(item.get("id", "")).strip() == target_id)
        ]
        if len(kept) != len(supplements):
            lecture["supplements"] = kept
            return True
    return False


def _teacher_source_snapshot(lecture: dict[str, Any]) -> list[dict[str, Any]]:
    """Capture immutable problem source fields for a cheap post-apply invariant check."""
    snapshot: list[dict[str, Any]] = []
    for problem in lecture.get("problems", []):
        if not isinstance(problem, dict):
            continue
        source = {
            key: deepcopy(value)
            for key, value in problem.items()
            if key == "statement" or key.startswith("teacher_")
        }
        snapshot.append({"id": str(problem.get("id", "")), "source": source})
    return snapshot


def _apply_one(
    lecture: dict[str, Any],
    repair: dict[str, Any],
    *,
    model: str,
) -> bool:
    action = str(repair.get("action", "keep"))
    target_id = str(repair.get("target_id", ""))
    content = str(repair.get("content", ""))
    issue_id = str(repair.get("issue_id", ""))
    if action == "replace_target":
        return _replace_target(lecture, target_id, content, model=model)
    if action == "append_supplement":
        return _append_supplement(
            lecture, target_id, content, issue_id=issue_id, model=model
        )
    if action == "append_summary":
        return _append_summary(lecture, content, issue_id=issue_id, model=model)
    if action == "remove_target":
        return _remove_target(lecture, target_id)
    if action == "keep":
        return True
    return False


def apply_repair_round(
    lecture: dict[str, Any],
    issues: list[dict[str, Any]],
    repairs: list[dict[str, Any]],
    *,
    round_index: int,
    model: str,
    invalid_issue_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Atomically apply one logical repair round and return its canonical business result.

    The model may *claim* an issue is resolved, but the core marks it resolved only after
    the requested action is valid and successfully applies to a candidate publication.
    If any otherwise-valid mutation cannot be applied, the whole mutation batch is
    discarded.  Issues already resolved by this same in-memory run are treated as
    already-applied, making repeated application idempotent for append/remove actions.
    """
    expected_model = repair_model(round_index)
    if expected_model is None:
        raise StageError(f"pedagogical repair round 越界: {round_index}")
    if model != expected_model:
        raise StageError(
            f"pedagogical repair round {round_index} 模型不匹配: {model!r} != {expected_model!r}"
        )

    invalid_ids = {str(x) for x in (invalid_issue_ids or []) if str(x)}
    candidate_lecture = deepcopy(lecture)
    candidate_issues = deepcopy(issues)
    source_before = _teacher_source_snapshot(lecture)
    by_id = {
        str(issue.get("pedagogical_issue_id", "")): issue
        for issue in candidate_issues
        if isinstance(issue, dict)
    }

    claimed_resolved: list[str] = []
    resolved: list[str] = []
    already_applied: list[str] = []
    mutation_failures: list[str] = []
    applied = 0

    for repair in repairs:
        issue_id = str(repair.get("issue_id", ""))
        issue = by_id.get(issue_id)
        if issue is None:
            raise StageError(f"pedagogical repair apply 找不到 issue: {issue_id}")

        if str(issue.get("status", "open")) == "resolved":
            already_applied.append(issue_id)
            continue

        if str(repair.get("claimed_status", repair.get("status", ""))) != "resolved":
            continue

        claimed_resolved.append(issue_id)
        if not _apply_one(candidate_lecture, repair, model=model):
            mutation_failures.append(issue_id)
            continue

        action = str(repair.get("action", "keep"))
        if action != "keep":
            applied += 1
        issue["status"] = "resolved"
        issue["pedagogical_repair"] = {
            "round": round_index,
            "model": model,
            "action": action,
        }
        resolved.append(issue_id)

    # A structurally valid response can still request an impossible/unsafe mutation.
    # In that case discard *all* candidate changes from this application batch.
    if mutation_failures or _teacher_source_snapshot(candidate_lecture) != source_before:
        invalid_ids.update(mutation_failures)
        remaining = [
            str(issue.get("pedagogical_issue_id", ""))
            for issue in unresolved_pedagogical_issues(issues)
            if str(issue.get("pedagogical_issue_id", ""))
        ]
        return {
            "round": round_index,
            "model": model,
            "status": REPAIR_INVALID,
            "claimed_resolved": sorted(claimed_resolved),
            "resolved": [],
            "unresolved": sorted(remaining),
            "invalid_issue_ids": sorted(invalid_ids),
            "already_applied": sorted(already_applied),
            "applied": 0,
        }

    # Commit only after the whole candidate batch passed validation and invariants.
    lecture.clear()
    lecture.update(candidate_lecture)
    issues[:] = candidate_issues

    remaining = [
        str(issue.get("pedagogical_issue_id", ""))
        for issue in unresolved_pedagogical_issues(issues)
        if str(issue.get("pedagogical_issue_id", ""))
    ]
    if not remaining:
        business_status = REPAIR_RESOLVED
    elif invalid_ids and not repairs:
        business_status = REPAIR_INVALID
    else:
        business_status = REPAIR_UNRESOLVED_NON_BLOCKING

    return {
        "round": round_index,
        "model": model,
        "status": business_status,
        "claimed_resolved": sorted(claimed_resolved),
        "resolved": sorted(resolved),
        "unresolved": sorted(remaining),
        "invalid_issue_ids": sorted(invalid_ids),
        "already_applied": sorted(already_applied),
        "applied": applied,
    }


def repair_summary(
    issues: list[dict[str, Any]],
    rounds: list[dict[str, Any]],
) -> dict[str, Any]:
    unresolved = [
        str(issue.get("pedagogical_issue_id", ""))
        for issue in unresolved_pedagogical_issues(issues)
    ]
    final_status = REPAIR_RESOLVED if not unresolved else REPAIR_UNRESOLVED_NON_BLOCKING
    return {
        "models": list(PEDAGOGICAL_REPAIR_ROUTE),
        "max_rounds": len(PEDAGOGICAL_REPAIR_ROUTE),
        "rounds": rounds,
        "status": final_status,
        "resolved": sum(1 for issue in issues if issue.get("status") == "resolved"),
        "unresolved": len(unresolved),
        "unresolved_issue_ids": sorted(x for x in unresolved if x),
        "complete": True,
        "complete_with_unresolved": bool(unresolved),
    }
