from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..completion.assessment import infer_solution_completeness
from ..errors import StageError

ALLOWED_REVIEW_STATUS = {"verified", "revised", "unresolved"}
RESOLVED_REVIEW_STATUS = {"verified", "revised"}


def collect_math_review_targets(lecture: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one immutable-source math target per problem with any solution process.

    Review must always start from source content, never from a previous reviewed/publication
    view.  This makes repeated review deterministic and prevents rewrite drift.
    """
    supplements_by_target: dict[str, list[dict[str, Any]]] = {}
    for supplement in lecture.get("supplements", []):
        if not isinstance(supplement, dict):
            continue
        target_id = str(supplement.get("target_id", "")).strip()
        if target_id:
            supplements_by_target.setdefault(target_id, []).append(supplement)

    targets: list[dict[str, Any]] = []
    for problem in lecture.get("problems", []):
        if not isinstance(problem, dict):
            continue
        pid = str(problem.get("id", "")).strip()
        if not pid:
            continue

        statement_obj = problem.get("statement")
        statement = str(statement_obj.get("content", "")) if isinstance(statement_obj, dict) else str(statement_obj or "")
        evidence_ids: set[str] = set()
        if isinstance(statement_obj, dict):
            evidence_ids.update(str(x) for x in statement_obj.get("evidence_ids", []))

        solution_items: list[dict[str, Any]] = []
        teacher_solution = problem.get("teacher_solution")
        if isinstance(teacher_solution, dict) and str(teacher_solution.get("content", "")).strip():
            eids = [str(x) for x in teacher_solution.get("evidence_ids", [])]
            evidence_ids.update(eids)
            solution_items.append({
                "target_id": f"{pid}.teacher_solution",
                "kind": "teacher_solution",
                "content": str(teacher_solution.get("content", "")),
                "evidence_ids": eids,
                "completeness": infer_solution_completeness(problem),
            })

        supplement_solution = problem.get("supplement_solution")
        if isinstance(supplement_solution, dict) and str(supplement_solution.get("content", "")).strip():
            eids = [str(x) for x in supplement_solution.get("evidence_ids", [])]
            evidence_ids.update(eids)
            solution_items.append({
                "target_id": f"{pid}.supplement_solution",
                "kind": "supplement_solution",
                "content": str(supplement_solution.get("content", "")),
                "evidence_ids": eids,
                "completeness": "complete",
            })

        for supplement in supplements_by_target.get(pid, []):
            if supplement.get("type") != "derived_solution":
                continue
            sid = str(supplement.get("id", "")).strip()
            content = str(supplement.get("content", "")).strip()
            if not sid or not content:
                continue
            eids = [str(x) for x in supplement.get("evidence_ids", [])]
            evidence_ids.update(eids)
            solution_items.append({
                "target_id": sid,
                "kind": "derived_solution",
                "content": content,
                "evidence_ids": eids,
                "completeness": "complete",
            })

        if not solution_items:
            continue

        answer_obj = problem.get("teacher_answer")
        answer_item = None
        if isinstance(answer_obj, dict) and str(answer_obj.get("content", "")).strip():
            eids = [str(x) for x in answer_obj.get("evidence_ids", [])]
            evidence_ids.update(eids)
            answer_item = {
                "target_id": f"{pid}.teacher_answer",
                "kind": "teacher_answer",
                "content": str(answer_obj.get("content", "")),
                "evidence_ids": eids,
            }

        targets.append({
            "target_id": pid,
            "kind": "problem_solution_review",
            "statement": statement,
            "solutions": solution_items,
            "answer": answer_item,
            "evidence_ids": sorted(evidence_ids),
        })
    return targets


def target_ids(target: dict[str, Any]) -> set[str]:
    ids = {
        str(item.get("target_id", ""))
        for item in target.get("solutions", [])
        if isinstance(item, dict) and item.get("target_id")
    }
    answer = target.get("answer")
    if isinstance(answer, dict) and answer.get("target_id"):
        ids.add(str(answer["target_id"]))
    return ids


def expected_solution_ids(targets: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("target_id", ""))
        for target in targets
        for item in target.get("solutions", [])
        if isinstance(item, dict) and item.get("target_id")
    }


def expected_answer_ids(targets: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for target in targets:
        answer = target.get("answer")
        if isinstance(answer, dict) and answer.get("target_id"):
            out.add(str(answer["target_id"]))
    return out


def _validate_items(raw: Any, *, expected: set[str], field: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise StageError(f"math review.{field} 必须为 list。")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise StageError(f"math review.{field}[{index}] 必须为 object。")
        target_id = str(item.get("target_id", "")).strip()
        status = str(item.get("status", "")).strip()
        content = str(item.get("content", "")).strip()
        if not target_id or target_id not in expected:
            raise StageError(f"math review.{field} 返回未知 target_id: {target_id!r}")
        if target_id in seen:
            raise StageError(f"math review.{field} 重复 target_id: {target_id}")
        if status not in ALLOWED_REVIEW_STATUS:
            raise StageError(f"math review.{field} status 非法: {status!r}")
        if status == "revised" and not content:
            raise StageError(f"math review.{field} {target_id} revised 时 content 不能为空。")
        # verified keeps immutable source; unresolved model text is deliberately ignored.
        normalized.append({
            "target_id": target_id,
            "status": status,
            "content": content if status == "revised" else "",
        })
        seen.add(target_id)

    missing = expected - seen
    if missing:
        raise StageError(f"math review.{field} 漏审 target_id: {', '.join(sorted(missing))}")
    return normalized


def validate_math_revision_response(data: dict[str, Any], targets: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "reviewed_solutions": _validate_items(
            data.get("reviewed_solutions"), expected=expected_solution_ids(targets), field="reviewed_solutions"
        ),
        "reviewed_answers": _validate_items(
            data.get("reviewed_answers", []), expected=expected_answer_ids(targets), field="reviewed_answers"
        ),
    }


def unresolved_target_ids(result: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for field in ("reviewed_solutions", "reviewed_answers"):
        for item in result.get(field, []):
            if isinstance(item, dict) and item.get("status") == "unresolved" and item.get("target_id"):
                out.add(str(item["target_id"]))
    return out


def filter_target_for_ids(target: dict[str, Any], ids: set[str]) -> dict[str, Any]:
    """Create a high-review target containing only unresolved items, but full problem context."""
    out = deepcopy(target)
    out["solutions"] = [
        item for item in out.get("solutions", [])
        if isinstance(item, dict) and str(item.get("target_id", "")) in ids
    ]
    answer = out.get("answer")
    if not (isinstance(answer, dict) and str(answer.get("target_id", "")) in ids):
        out["answer"] = None
    out["escalated_target_ids"] = sorted(ids)
    return out


def source_items_by_id(targets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for target in targets:
        for item in target.get("solutions", []):
            if isinstance(item, dict) and item.get("target_id"):
                out[str(item["target_id"])] = item
        answer = target.get("answer")
        if isinstance(answer, dict) and answer.get("target_id"):
            out[str(answer["target_id"])] = answer
    return out


def _result_map(result: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(result, dict):
        return out
    for field in ("reviewed_solutions", "reviewed_answers"):
        for item in result.get(field, []):
            if isinstance(item, dict) and item.get("target_id"):
                out[str(item["target_id"])] = item
    return out


def final_review_item(
    target_id: str,
    *,
    medium_result: dict[str, Any] | None,
    high_result: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    medium = _result_map(medium_result).get(target_id)
    high = _result_map(high_result).get(target_id)
    if medium is None:
        return None, None
    if medium.get("status") != "unresolved":
        return medium, "sol-medium"
    if high is not None:
        return high, "sol-high"
    return medium, "sol-medium"


def _source_content(source: dict[str, Any]) -> str:
    return str(source.get("content", ""))


def resolved_content(source: dict[str, Any], result_item: dict[str, Any] | None) -> str:
    """Return publication-safe content. Never use model text from unresolved/verified."""
    if isinstance(result_item, dict) and result_item.get("status") == "revised":
        return str(result_item.get("content", ""))
    return _source_content(source)


def _candidate_priority(kind: str, completeness: str, status: str) -> int:
    resolved = status in RESOLVED_REVIEW_STATUS
    if kind == "teacher_solution" and completeness == "complete" and resolved:
        return 100
    if kind in {"derived_solution", "supplement_solution"} and completeness == "complete" and resolved:
        return 90
    if kind == "teacher_solution" and completeness == "complete":
        return 70
    if kind == "teacher_solution":
        return 60
    if kind in {"derived_solution", "supplement_solution"} and resolved:
        return 50
    return 40


def _problem_sources(target: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in target.get("solutions", []):
        if isinstance(item, dict) and item.get("target_id"):
            out[str(item["target_id"])] = item
    answer = target.get("answer")
    if isinstance(answer, dict) and answer.get("target_id"):
        out[str(answer["target_id"])] = answer
    return out


def apply_math_review_cascade(
    lecture: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    medium_results: dict[str, dict[str, Any]],
    high_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Apply review metadata and build one publication solution per problem.

    Source fields are never overwritten.  Medium unresolved targets may be replaced by
    High results.  If High is still unresolved, model text is ignored and the problem is
    marked for the explicit publication note instead of blocking PDF generation.
    """
    problems = {
        str(problem.get("id", "")): problem
        for problem in lecture.get("problems", [])
        if isinstance(problem, dict) and problem.get("id")
    }
    supplements = {
        str(item.get("id", "")): item
        for item in lecture.get("supplements", [])
        if isinstance(item, dict) and item.get("id")
    }

    counts = {"verified": 0, "revised": 0, "unresolved": 0}
    reviewed_targets: set[str] = set()
    resolved_targets: set[str] = set()
    escalated_targets: set[str] = set()
    unresolved_targets: set[str] = set()
    problems_with_unresolved: set[str] = set()

    for target in targets:
        pid = str(target.get("target_id", ""))
        problem = problems.get(pid)
        if problem is None:
            raise StageError(f"math review 无法定位题目: {pid}")
        medium = medium_results.get(pid)
        high = high_results.get(pid)
        if medium is None:
            raise StageError(f"math review 缺少 Sol Medium 结果: {pid}")

        source_map = _problem_sources(target)
        review_records: dict[str, Any] = {}
        candidates: list[dict[str, Any]] = []

        for solution in target.get("solutions", []):
            if not isinstance(solution, dict):
                continue
            tid = str(solution.get("target_id", ""))
            result_item, model = final_review_item(tid, medium_result=medium, high_result=high)
            if result_item is None:
                raise StageError(f"math review 缺少 target 结果: {tid}")
            status = str(result_item.get("status", ""))
            reviewed_targets.add(tid)
            counts[status] += 1
            if _result_map(medium).get(tid, {}).get("status") == "unresolved":
                escalated_targets.add(tid)
            if status in RESOLVED_REVIEW_STATUS:
                resolved_targets.add(tid)
            else:
                unresolved_targets.add(tid)
                problems_with_unresolved.add(pid)
            content = resolved_content(solution, result_item)
            record = {
                "status": status,
                "model": model,
                "source_target_id": tid,
                "content": content if status == "revised" else None,
            }
            review_records[tid] = record
            candidates.append({
                "target_id": tid,
                "kind": str(solution.get("kind", "solution")),
                "completeness": str(solution.get("completeness", "complete")),
                "status": status,
                "model": model,
                "content": content,
            })

            # Backward-compatible per-supplement review metadata, without changing source content.
            if tid in supplements and supplements[tid].get("type") == "derived_solution":
                sup = supplements[tid]
                sup["math_review_status"] = "verified" if status in RESOLVED_REVIEW_STATUS else "unresolved"
                sup["math_review_result"] = status
                sup["math_review_model"] = model
                sup["status"] = "confirmed" if status in RESOLVED_REVIEW_STATUS else "uncertain"
                sup.pop("reviewed_content", None)

        answer = target.get("answer")
        publication_answer = None
        if isinstance(answer, dict) and answer.get("target_id"):
            tid = str(answer["target_id"])
            result_item, model = final_review_item(tid, medium_result=medium, high_result=high)
            if result_item is None:
                raise StageError(f"math review 缺少答案结果: {tid}")
            status = str(result_item.get("status", ""))
            reviewed_targets.add(tid)
            counts[status] += 1
            if _result_map(medium).get(tid, {}).get("status") == "unresolved":
                escalated_targets.add(tid)
            if status in RESOLVED_REVIEW_STATUS:
                resolved_targets.add(tid)
            else:
                unresolved_targets.add(tid)
                problems_with_unresolved.add(pid)
            content = resolved_content(answer, result_item)
            review_records[tid] = {
                "status": status,
                "model": model,
                "source_target_id": tid,
                "content": content if status == "revised" else None,
            }
            publication_answer = {
                "content": content,
                "source_target_id": tid,
                "review_status": status,
                "review_model": model,
            }

        candidates.sort(
            key=lambda item: _candidate_priority(
                str(item.get("kind", "")), str(item.get("completeness", "")), str(item.get("status", ""))
            ),
            reverse=True,
        )
        publication_solution = None
        if candidates:
            chosen = candidates[0]
            publication_solution = {
                "content": chosen["content"],
                "source_target_id": chosen["target_id"],
                "source_kind": chosen["kind"],
                "review_status": chosen["status"],
                "review_model": chosen["model"],
            }

        problem["math_review"] = {
            "targets": review_records,
            "has_unresolved": pid in problems_with_unresolved,
        }
        if publication_solution:
            problem["publication_solution"] = publication_solution
        else:
            problem.pop("publication_solution", None)
        if publication_answer:
            problem["publication_answer"] = publication_answer
        else:
            problem.pop("publication_answer", None)
        problem["math_review_unresolved"] = pid in problems_with_unresolved
        # Old direct-review fields must not influence a later review/render run.
        problem.pop("reviewed_solution", None)
        problem.pop("reviewed_supplement_solution", None)
        problem.pop("reviewed_answer", None)

    return {
        "reviewed_targets": sorted(reviewed_targets),
        "resolved_targets": sorted(resolved_targets),
        "escalated_targets": sorted(escalated_targets),
        "unresolved_targets": sorted(unresolved_targets),
        "problems_with_unresolved": sorted(problems_with_unresolved),
        "verified": counts["verified"],
        "revised": counts["revised"],
        "unresolved": counts["unresolved"],
        "complete": True,
        "complete_with_unresolved": bool(unresolved_targets),
    }


def factual_context_for_problem(issues: list[dict[str, Any]], problem_id: str) -> list[dict[str, Any]]:
    prefix = problem_id + "."
    out: list[dict[str, Any]] = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("target_id", ""))
        if target_id == problem_id or target_id.startswith(prefix):
            out.append(item)
    return out


def _portable_to_absolute(path_value: str, workspace_root: Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else workspace_root / path


def select_math_image_paths(
    lecture: dict[str, Any],
    target: dict[str, Any],
    timeline: list[dict[str, Any]],
    *,
    workspace_root: Path,
    max_images: int = 2,
) -> list[str]:
    """Select at most the problem figure and one useful board/evidence frame."""
    pid = str(target.get("target_id", ""))
    out: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if not value or len(out) >= max(1, int(max_images)):
            return
        path = _portable_to_absolute(str(value), workspace_root).resolve()
        key = str(path)
        if key in seen or not path.exists() or not path.is_file():
            return
        seen.add(key)
        out.append(key)

    for figure in lecture.get("figures", []):
        if not isinstance(figure, dict):
            continue
        if str(figure.get("problem_id") or figure.get("target_id") or "") != pid:
            continue
        add(figure.get("evidence_path"))
        if len(out) >= max_images:
            return out

    evidence_ids = {str(x) for x in target.get("evidence_ids", [])}
    for evidence in timeline:
        if not isinstance(evidence, dict) or str(evidence.get("id", "")) not in evidence_ids:
            continue
        frames = [x for x in evidence.get("frames", []) if isinstance(x, dict) and x.get("path")]
        frames.sort(key=lambda x: float(x.get("time", 0.0) or 0.0), reverse=True)
        for frame in frames:
            add(frame.get("path"))
            if len(out) >= max_images:
                return out
    return out


def resolve_api_llm_config(math_cfg: dict[str, Any], logical_model: str) -> dict[str, Any]:
    escalation = str(math_cfg.get("escalation_model", "sol-high"))
    if logical_model == escalation and isinstance(math_cfg.get("high_llm"), dict):
        cfg = deepcopy(math_cfg["high_llm"])
    else:
        cfg = deepcopy(math_cfg.get("llm", {}))
    aliases = math_cfg.get("api_model_aliases", {})
    alias = aliases.get(logical_model) if isinstance(aliases, dict) else None
    if alias:
        cfg["model"] = str(alias)
    elif not str(cfg.get("model", "")).strip() or logical_model == "sol-high":
        # For an OpenAI-compatible endpoint that uses different model IDs, set
        # review.math.api_model_aliases in the user config.
        cfg["model"] = logical_model
    return cfg


def render_math_user(
    prompt: dict[str, Any],
    target: dict[str, Any],
    *,
    evidence: list[dict[str, Any]],
    factual_issues: list[dict[str, Any]],
    image_paths: list[str],
) -> str:
    import json

    user = str(prompt.get("user", ""))
    user = user.replace("{{TARGETS_JSON}}", json.dumps([target], ensure_ascii=False, indent=2))
    user = user.replace("{{EVIDENCE_JSON}}", json.dumps(evidence, ensure_ascii=False, indent=2))
    user = user.replace("{{FACTUAL_JSON}}", json.dumps(factual_issues, ensure_ascii=False, indent=2))
    user = user.replace("{{IMAGE_PATHS_JSON}}", json.dumps(image_paths, ensure_ascii=False, indent=2))
    return user


def math_problem_id_from_target_id(target_id: str) -> str:
    if "." in target_id and not target_id.startswith("sup_"):
        return target_id.split(".", 1)[0]
    return ""
