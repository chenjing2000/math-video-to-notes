from __future__ import annotations

from typing import Any, Iterable

from ..errors import StageError


VALID_STATUS = {"confirmed", "probable", "uncertain"}
VALID_ORIGIN = {"video", "reconstructed"}

VALID_SOLUTION_COMPLETENESS = {"complete", "incomplete", "missing", "uncertain", "not_applicable"}


def validate_problem_metadata(data: dict[str, Any]) -> None:
    for obj in _walk(data):
        if "solution_completeness" in obj:
            value = str(obj.get("solution_completeness", ""))
            if value not in VALID_SOLUTION_COMPLETENESS:
                raise StageError(f"非法 solution_completeness={value!r}。")
        if "requires_solution" in obj and not isinstance(obj.get("requires_solution"), bool):
            raise StageError("requires_solution 必须为 boolean。")


def _walk(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


def validate_evidence_references(
    data: dict[str, Any],
    *,
    valid_evidence_ids: set[str],
) -> None:
    for obj in _walk(data):
        if "evidence_ids" in obj:
            ids = obj["evidence_ids"]
            if not isinstance(ids, list):
                raise StageError("evidence_ids 必须为数组。")
            unknown = [str(x) for x in ids if str(x) not in valid_evidence_ids]
            if unknown:
                raise StageError(
                    "LLM 引用了不存在的 evidence_ids: " + ", ".join(unknown)
                )
        if "figure_evidence_ids" in obj:
            ids = obj["figure_evidence_ids"]
            if not isinstance(ids, list):
                raise StageError("figure_evidence_ids 必须为数组。")
            unknown = [str(x) for x in ids if str(x) not in valid_evidence_ids]
            if unknown:
                raise StageError(
                    "LLM 引用了不存在的 figure_evidence_ids: "
                    + ", ".join(unknown)
                )


def validate_origins_and_status(data: dict[str, Any]) -> None:
    for obj in _walk(data):
        origin = obj.get("origin")
        if origin is not None and origin not in VALID_ORIGIN:
            raise StageError(f"Sprint 5 禁止 origin={origin!r}。")
        status = obj.get("status")
        if status is not None and status not in VALID_STATUS:
            raise StageError(f"非法 reconstruction status={status!r}。")


def validate_chunk(data: dict[str, Any], valid_evidence_ids: set[str]) -> None:
    for key in ("topics", "problems", "section_hints"):
        if key not in data or not isinstance(data[key], list):
            raise StageError(f"Chunk reconstruction 缺少数组字段: {key}")
    validate_evidence_references(data, valid_evidence_ids=valid_evidence_ids)
    validate_origins_and_status(data)
    validate_problem_metadata(data)


def validate_lecture_draft(
    data: dict[str, Any],
    valid_evidence_ids: set[str],
) -> None:
    if data.get("schema_version") != "1.0":
        raise StageError("lecture.json schema_version 必须为 1.0。")
    if data.get("stage") != "reconstruction_draft":
        raise StageError("lecture.json stage 必须为 reconstruction_draft。")
    for key in ("metadata", "overview", "sections", "problems", "supplements"):
        if key not in data:
            raise StageError(f"lecture.json 缺少字段: {key}")
    if data.get("supplements") != []:
        raise StageError("Sprint 5 禁止生成 supplements。")
    if not isinstance(data.get("sections"), list):
        raise StageError("sections 必须为数组。")
    if not isinstance(data.get("problems"), list):
        raise StageError("problems 必须为数组。")
    validate_evidence_references(data, valid_evidence_ids=valid_evidence_ids)
    validate_origins_and_status(data)
    validate_problem_metadata(data)
