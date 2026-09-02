from __future__ import annotations

from typing import Any


VALID_COMPLETENESS = {"complete", "incomplete", "missing", "uncertain", "not_applicable"}
INCOMPLETE_MARKERS = (
    "未完整",
    "不完整",
    "未讲完",
    "没有讲完",
    "未呈现后续",
    "后续证明未",
    "后续过程未",
    "分块证据未完整",
    "未给出完整",
)
SOLUTION_CUES = ("求证", "证明", "求解", "求值", "计算", "解：")


def infer_requires_solution(problem: dict[str, Any]) -> bool:
    explicit = problem.get("requires_solution")
    if isinstance(explicit, bool):
        return explicit

    if isinstance(problem.get("teacher_solution"), dict) or isinstance(problem.get("teacher_answer"), dict):
        return True

    statement = problem.get("statement")
    content = str(statement.get("content", "")) if isinstance(statement, dict) else ""
    return any(cue in content for cue in SOLUTION_CUES)


def infer_solution_completeness(problem: dict[str, Any]) -> str:
    explicit = str(problem.get("solution_completeness", "")).strip()
    if explicit in VALID_COMPLETENESS:
        return explicit

    if not infer_requires_solution(problem):
        return "not_applicable"

    solution = problem.get("teacher_solution")
    if not isinstance(solution, dict) or not str(solution.get("content", "")).strip():
        return "missing"

    content = str(solution.get("content", ""))
    if any(marker in content for marker in INCOMPLETE_MARKERS):
        return "incomplete"

    status = str(solution.get("status", "")).strip()
    if status == "uncertain":
        return "uncertain"

    return "complete"


def annotate_problem_assessment(problem: dict[str, Any]) -> dict[str, Any]:
    problem["requires_solution"] = infer_requires_solution(problem)
    problem["solution_completeness"] = infer_solution_completeness(problem)
    return problem
