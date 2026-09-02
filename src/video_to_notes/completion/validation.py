from __future__ import annotations

from typing import Any

from ..errors import StageError


ALLOWED_REASONS = {
    "missing_content",
    "incomplete_explanation",
    "unclear_explanation",
    "pedagogical_bridge",
}

ALLOWED_TYPES = {
    "derived_solution",
    "explanation",
    "bridge",
    "missing_content",
}


def collect_valid_targets(lecture: dict[str, Any]) -> set[str]:
    targets: set[str] = set()

    for section in lecture.get("sections", []):
        sid = section.get("id")
        if sid:
            targets.add(str(sid))
        for block in section.get("blocks", []):
            bid = block.get("id")
            if bid:
                targets.add(str(bid))

    for problem in lecture.get("problems", []):
        pid = problem.get("id")
        if pid:
            targets.add(str(pid))

    return targets


def validate_completion_items(
    items: list[dict[str, Any]],
    *,
    valid_targets: set[str],
    reject_unreferenced_targets: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise StageError("completion items 必须为 list。")

    validated: list[dict[str, Any]] = []

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise StageError(f"completion item #{idx} 不是 object。")

        target_id = str(item.get("target_id", "")).strip()
        reason = str(item.get("reason", "")).strip()
        why_needed = str(item.get("why_needed", "")).strip()
        content = str(item.get("content", "")).strip()
        raw_type = item.get("type")
        item_type = str(raw_type).strip() if raw_type is not None else ""

        if not target_id:
            raise StageError(f"completion item #{idx} 缺少 target_id。")

        if reject_unreferenced_targets and target_id not in valid_targets:
            raise StageError(
                f"completion item #{idx} 引用了不存在的 target_id: {target_id}"
            )

        if reason not in ALLOWED_REASONS:
            raise StageError(f"completion item #{idx} reason 非法: {reason}")

        if item_type and item_type not in ALLOWED_TYPES:
            raise StageError(f"completion item #{idx} type 非法: {item_type}")

        if item_type == "derived_solution" and reason not in {
            "incomplete_explanation",
            "missing_content",
            "unclear_explanation",
        }:
            raise StageError(
                f"completion item #{idx} derived_solution 的 reason 不合理: {reason}"
            )

        if not why_needed:
            raise StageError(f"completion item #{idx} 缺少 why_needed。")

        if not content:
            raise StageError(f"completion item #{idx} content 为空。")

        result: dict[str, Any] = {
            "id": f"sup_{len(validated) + 1:03d}",
            "target_id": target_id,
            "reason": reason,
            "why_needed": why_needed,
            "content": content,
            "origin": "supplement",
            "status": "confirmed",
        }

        # Backward compatibility: legacy completion responses had no `type`.
        # Sprint 10 prompts always emit it, but old file/API responses remain readable.
        if item_type:
            result["type"] = item_type
        if item_type == "derived_solution":
            result["status"] = "probable"
            result["math_review_status"] = "pending"
            basis = item.get("derivation_basis")
            if isinstance(basis, list):
                result["derivation_basis"] = [str(x) for x in basis if str(x).strip()]

        validated.append(result)

    return validated
