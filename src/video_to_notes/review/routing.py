from __future__ import annotations

from collections import defaultdict
from typing import Any


def _content_item(
    target_id: str,
    *,
    kind: str,
    content: Any,
    origin: str | None = None,
    status: str | None = None,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "kind": kind,
        "content": content,
        "origin": origin,
        "status": status,
        "evidence_ids": evidence_ids or [],
    }


def collect_all_target_ids(lecture: dict[str, Any]) -> set[str]:
    ids: set[str] = {"lecture"}

    for section in lecture.get("sections", []):
        sid = str(section.get("id", "")).strip()
        if sid:
            ids.add(sid)
        for block in section.get("blocks", []):
            bid = str(block.get("id", "")).strip()
            if bid:
                ids.add(bid)

    for problem in lecture.get("problems", []):
        pid = str(problem.get("id", "")).strip()
        if not pid:
            continue
        ids.add(pid)
        for field in (
            "statement",
            "analysis",
            "teacher_solution",
            "supplement_solution",
            "teacher_answer",
        ):
            value = problem.get(field)
            if value is not None:
                ids.add(f"{pid}.{field}")

    for supplement in lecture.get("supplements", []):
        sid = str(supplement.get("id", "")).strip()
        if sid:
            ids.add(sid)

    return ids


def collect_factual_targets(
    lecture: dict[str, Any],
    *,
    trigger_statuses: set[str],
    always_review_problem_fields: set[str],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        tid = item["target_id"]
        if tid not in seen:
            seen.add(tid)
            targets.append(item)

    for section in lecture.get("sections", []):
        for block in section.get("blocks", []):
            status = str(block.get("status", ""))
            if status in trigger_statuses:
                bid = str(block.get("id", "")).strip()
                if bid:
                    add(_content_item(
                        bid,
                        kind="section_block",
                        content=block.get("content"),
                        origin=block.get("origin"),
                        status=block.get("status"),
                        evidence_ids=list(block.get("evidence_ids", [])),
                    ))

    for problem in lecture.get("problems", []):
        pid = str(problem.get("id", "")).strip()
        if not pid:
            continue
        for field in (
            "statement",
            "analysis",
            "teacher_solution",
            "teacher_answer",
        ):
            value = problem.get(field)
            if value is None or not isinstance(value, dict):
                continue
            status = str(value.get("status", ""))
            if field in always_review_problem_fields or status in trigger_statuses:
                add(_content_item(
                    f"{pid}.{field}",
                    kind=f"problem_{field}",
                    content=value.get("content"),
                    origin=value.get("origin"),
                    status=value.get("status"),
                    evidence_ids=list(value.get("evidence_ids", [])),
                ))

    return targets


def collect_math_targets(
    lecture: dict[str, Any],
    *,
    review_all_problems: bool,
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    supplements_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for supplement in lecture.get("supplements", []):
        if not isinstance(supplement, dict):
            continue
        target_id = str(supplement.get("target_id", "")).strip()
        if target_id:
            supplements_by_target[target_id].append(supplement)

    if review_all_problems:
        for problem in lecture.get("problems", []):
            pid = str(problem.get("id", "")).strip()
            if pid:
                targets.append({
                    "target_id": pid,
                    "kind": "problem",
                    "content": {
                        "problem": problem,
                        "supplements": supplements_by_target.get(pid, []),
                    },
                })

    for section in lecture.get("sections", []):
        for block in section.get("blocks", []):
            block_type = str(block.get("type", ""))
            if block_type in {"theorem", "property", "method", "knowledge"}:
                bid = str(block.get("id", "")).strip()
                content = str(block.get("content", ""))
                if bid and any(ch in content for ch in "=<>±√∠°^_\\"):
                    targets.append({
                        "target_id": bid,
                        "kind": "math_block",
                        "content": block,
                    })

    return targets
