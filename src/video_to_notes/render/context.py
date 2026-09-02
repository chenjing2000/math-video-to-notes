from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_render_context(lecture: dict[str, Any]) -> dict[str, Any]:
    problems_by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unassigned_problems: list[dict[str, Any]] = []

    section_ids = {
        str(section.get("id"))
        for section in lecture.get("sections", [])
        if section.get("id")
    }

    for problem in lecture.get("problems", []):
        section_id = problem.get("section_id")
        if section_id and str(section_id) in section_ids:
            problems_by_section[str(section_id)].append(problem)
        else:
            unassigned_problems.append(problem)

    supplements_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for supplement in lecture.get("supplements", []):
        target_id = str(supplement.get("target_id", "")).strip()
        if target_id:
            supplements_by_target[target_id].append(supplement)

    issues_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in lecture.get("review", {}).get("issues", []):
        target_id = str(issue.get("target_id", "")).strip()
        if target_id:
            issues_by_target[target_id].append(issue)

    figures_by_problem: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for figure in lecture.get("figures", []):
        target_id = (
            figure.get("problem_id")
            or figure.get("target_id")
        )
        if target_id:
            figures_by_problem[str(target_id)].append(figure)

    return {
        "lecture": lecture,
        "problems_by_section": dict(problems_by_section),
        "unassigned_problems": unassigned_problems,
        "supplements_by_target": dict(supplements_by_target),
        "issues_by_target": dict(issues_by_target),
        "figures_by_problem": dict(figures_by_problem),
    }
