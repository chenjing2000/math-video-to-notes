from __future__ import annotations

from typing import Any

from ..errors import StageError


ALLOWED_REVIEW_TYPES = {"factual", "math", "pedagogical"}
ALLOWED_SEVERITIES = {"info", "warning", "error"}
ALLOWED_ISSUE_STATUS = {
    "open",
    "resolved",
    "accepted_source",
    "accepted_review",
}


def validate_raw_issues(
    raw_issues: Any,
    *,
    review_type: str,
    valid_target_ids: set[str],
    reject_unreferenced_targets: bool = True,
) -> list[dict[str, Any]]:
    if review_type not in ALLOWED_REVIEW_TYPES:
        raise StageError(f"未知 review_type: {review_type}")

    if not isinstance(raw_issues, list):
        raise StageError(f"{review_type} reviewer 的 issues 必须为 list。")

    result: list[dict[str, Any]] = []

    for index, raw in enumerate(raw_issues):
        if not isinstance(raw, dict):
            raise StageError(
                f"{review_type} issue #{index} 不是 object。"
            )

        target_id = str(raw.get("target_id", "")).strip()
        severity = str(raw.get("severity", "warning")).strip()
        label = str(raw.get("label", "other")).strip() or "other"
        message = str(raw.get("message", "")).strip()

        if not target_id:
            raise StageError(
                f"{review_type} issue #{index} 缺少 target_id。"
            )

        if reject_unreferenced_targets and target_id not in valid_target_ids:
            raise StageError(
                f"{review_type} reviewer 引用了不存在的 target_id: {target_id}"
            )

        if severity not in ALLOWED_SEVERITIES:
            raise StageError(
                f"{review_type} issue #{index} severity 非法: {severity}"
            )

        if not message:
            raise StageError(
                f"{review_type} issue #{index} message 为空。"
            )

        result.append({
            "target_id": target_id,
            "review_type": review_type,
            "severity": severity,
            "status": "open",
            "label": label,
            "message": message,
            "source_value": raw.get("source_value"),
            "review_value": raw.get("review_value"),
        })

    return result


def assign_issue_ids(
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {"id": f"rv_{index:03d}", **issue}
        for index, issue in enumerate(issues, start=1)
    ]
