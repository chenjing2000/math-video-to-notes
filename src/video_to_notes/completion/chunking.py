from __future__ import annotations

from copy import deepcopy
from typing import Any

from .assessment import annotate_problem_assessment


def make_completion_chunks(
    lecture: dict[str, Any],
    *,
    max_items_per_call: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for section in lecture.get("sections", []):
        items.append({
            "kind": "section",
            "id": section.get("id"),
            "data": section,
        })

    for problem in lecture.get("problems", []):
        enriched = annotate_problem_assessment(deepcopy(problem))
        items.append({
            "kind": "problem",
            "id": enriched.get("id"),
            "data": enriched,
        })

    if not items:
        return [{"items": []}]

    size = max(1, int(max_items_per_call))
    return [
        {"items": items[i:i + size]}
        for i in range(0, len(items), size)
    ]
