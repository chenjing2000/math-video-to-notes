from __future__ import annotations

from pathlib import Path
from typing import Any


VISUAL_CUES = ("如图", "图中", "下图", "图示", "见图")
GEOMETRY_CUES = ("三角形", "中点", "中线", "延长", "连接", "平行", "垂直", "角", "线段", "四边形", "圆", "\\triangle", "\\angle", "△", "∠")


def statement_needs_figure(problem: dict[str, Any]) -> bool:
    statement = problem.get("statement")
    if not isinstance(statement, dict):
        return False
    content = str(statement.get("content", ""))
    if any(cue in content for cue in VISUAL_CUES):
        return True
    # Geometry problems often depend on the diagram even when the spoken/written
    # statement does not literally say “如图”. Require at least two independent
    # geometry cues to avoid attaching arbitrary screenshots to ordinary algebra.
    hits = sum(1 for cue in GEOMETRY_CUES if cue in content)
    return hits >= 2


def _statement_evidence_ids(problem: dict[str, Any]) -> list[str]:
    statement = problem.get("statement")
    if not isinstance(statement, dict):
        return []
    ids = statement.get("evidence_ids", [])
    return [str(x) for x in ids] if isinstance(ids, list) else []


def _figure_evidence_ids(problem: dict[str, Any]) -> list[str]:
    ids = problem.get("figure_evidence_ids", [])
    return [str(x) for x in ids] if isinstance(ids, list) else []


def _choose_problem_frame(evidence: dict[str, Any]) -> dict[str, Any] | None:
    frames = evidence.get("frames", [])
    if not isinstance(frames, list) or not frames:
        return None
    clean = [x for x in frames if isinstance(x, dict) and x.get("path")]
    if not clean:
        return None
    clean.sort(key=lambda x: float(x.get("time", 0.0)))
    # For a problem illustration, prefer the earliest high-resolution state.
    # This usually contains the clean problem/diagram before later annotations.
    return clean[0]


def _portable_path(path_value: str, workspace_root: Path) -> str:
    path = Path(path_value)
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.resolve().relative_to(workspace_root.resolve()))
    except Exception:
        return str(path)


def bind_problem_figures(
    lecture: dict[str, Any],
    timeline: list[dict[str, Any]],
    *,
    workspace_root: Path,
    infer_from_statement: bool = True,
    max_figures_per_problem: int = 2,
) -> dict[str, Any]:
    """Bind problem figure evidence IDs to actual evidence-frame files.

    The LLM only chooses evidence segment IDs. File/frame resolution is deterministic,
    which prevents fabricated paths from entering lecture.json.
    """

    timeline_by_id = {
        str(item.get("id")): item
        for item in timeline
        if isinstance(item, dict) and item.get("id")
    }

    # Preserve manually supplied/non-auto figures. Auto-bound figures are rebuilt so
    # rerunning reconstruction/render cannot accumulate duplicates.
    existing = [
        fig for fig in lecture.get("figures", [])
        if isinstance(fig, dict) and fig.get("source") != "evidence_binding"
    ]
    auto_figures: list[dict[str, Any]] = []
    bound_problem_ids: list[str] = []
    inferred_problem_ids: list[str] = []
    unresolved_problem_ids: list[str] = []

    limit = max(1, int(max_figures_per_problem))

    for problem in lecture.get("problems", []):
        if not isinstance(problem, dict):
            continue
        pid = str(problem.get("id", "")).strip()
        if not pid:
            continue

        evidence_ids = _figure_evidence_ids(problem)
        inferred = False
        if not evidence_ids and infer_from_statement and statement_needs_figure(problem):
            evidence_ids = _statement_evidence_ids(problem)
            if evidence_ids:
                problem["figure_evidence_ids"] = evidence_ids
                inferred = True
                inferred_problem_ids.append(pid)

        selected: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        seen_frames: set[str] = set()
        for eid in evidence_ids:
            evidence = timeline_by_id.get(eid)
            if evidence is None:
                continue
            frame = _choose_problem_frame(evidence)
            if frame is None:
                continue
            frame_id = str(frame.get("id", ""))
            key = frame_id or str(frame.get("path"))
            if key in seen_frames:
                continue
            seen_frames.add(key)
            selected.append((eid, evidence, frame))
            if len(selected) >= limit:
                break

        if selected:
            bound_problem_ids.append(pid)
            for index, (eid, evidence, frame) in enumerate(selected, start=1):
                timestamp = float(frame.get("time", evidence.get("start", 0.0)) or 0.0)
                auto_figures.append({
                    "id": f"fig_{pid}_{index:02d}",
                    "target_id": pid,
                    "problem_id": pid,
                    "role": "problem_figure",
                    "source": "evidence_binding",
                    "evidence_id": eid,
                    "frame_id": frame.get("id"),
                    "evidence_path": _portable_path(str(frame["path"]), workspace_root),
                    "timestamp": timestamp,
                    "caption": "题目图" if index == 1 else f"题目图 {index}",
                    "width": "0.78",
                    "inferred_from_statement": inferred,
                })
        elif evidence_ids or statement_needs_figure(problem):
            unresolved_problem_ids.append(pid)

    lecture["figures"] = existing + auto_figures
    return {
        "figures_bound": len(auto_figures),
        "problems_bound": sorted(set(bound_problem_ids)),
        "problems_inferred": sorted(set(inferred_problem_ids)),
        "problems_unresolved": sorted(set(unresolved_problem_ids)),
    }
