from __future__ import annotations

import json
from pathlib import Path

from video_to_notes.config import load_config
from video_to_notes.handoff.reconstruction import prepare_reconstruction
from video_to_notes.performance import build_performance_report, record_handoff_prepare, record_stage, request_metrics
from video_to_notes.util import atomic_write_json, read_json


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "lesson"
    for rel in ("evidence", "responses/reconstruction", "tasks/reconstruction", "reports", "lecture"):
        (ws / rel).mkdir(parents=True, exist_ok=True)
    atomic_write_json(ws / "project.json", {
        "source": {"sha256": "abc123", "original_path": "lesson.mp4"},
        "project_name": "lesson",
    })
    return ws


def _timeline(ws: Path, text: str = "定义内容") -> None:
    atomic_write_json(ws / "evidence" / "timeline.json", {
        "timeline": [{
            "id": "ev_0000",
            "start": 0.0,
            "end": 10.0,
            "visual_type": "stable_slide",
            "frame_ids": [],
            "frames": [],
            "transcript_text": text,
            "confidence": 0.9,
            "status": "confirmed",
        }]
    })


def _chunk_response(rid: str) -> dict:
    return {
        "request_id": rid,
        "topics": [{"title": "定义", "content": "定义内容", "origin": "video", "evidence_ids": ["ev_0000"], "status": "confirmed"}],
        "problems": [],
        "section_hints": [{"title": "第一节", "evidence_ids": ["ev_0000"]}],
    }


def _merge_response(rid: str) -> dict:
    return {
        "request_id": rid,
        "schema_version": "1.0",
        "stage": "reconstruction_draft",
        "metadata": {},
        "overview": {"topic": "测试", "main_line": "定义", "core_methods": [], "learning_objectives": []},
        "sections": [],
        "problems": [],
        "supplements": [],
        "figures": [],
        "summary": [],
        "review": {"issues": []},
    }


def test_performance_report_counts_reuse(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    request = {
        "request_id": "r1",
        "task_type": "review_math",
        "required_model": "sol",
        "system": "check",
        "user": "proof image.jpg",
    }
    metrics = request_metrics(request)
    assert metrics["input_characters"] > 0
    assert metrics["images_sent"] == 1

    record_stage(ws, "visual", 12.5)
    record_handoff_prepare(ws, "review", input_id="i1", requests={"math.json": request}, reused_outputs={"math.json"})
    report = build_performance_report(ws)
    assert report["stage_summary"]["visual"]["runs"] == 1
    assert report["llm"]["requests_generated"] == 1
    assert report["llm"]["requests_reused"] == 1
    assert report["llm"]["avoided_input_characters"] == metrics["input_characters"]
    assert (ws / "reports" / "performance_report.md").exists()


def test_reconstruction_prepare_reuses_exact_responses_and_invalidates_merge_when_chunk_missing(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _timeline(ws)
    config = load_config()

    first = prepare_reconstruction(workspace_root=ws, config=config)
    chunk_req = json.loads((ws / "tasks/reconstruction/chunk_0000.request.json").read_text(encoding="utf-8"))
    merge_req = json.loads((ws / "tasks/reconstruction/merge.request.json").read_text(encoding="utf-8"))
    atomic_write_json(ws / "responses/reconstruction/chunk_0000.json", _chunk_response(chunk_req["request_id"]))
    atomic_write_json(ws / "responses/reconstruction/lecture.json", _merge_response(merge_req["request_id"]))

    second = prepare_reconstruction(workspace_root=ws, config=config)
    assert set(second["reused_outputs"]) == {"chunk_0000.json", "lecture.json"}
    assert (ws / "responses/reconstruction/lecture.json").exists()

    # Simulate one missing/invalid chunk: the old merge must not survive prepare.
    (ws / "responses/reconstruction/chunk_0000.json").unlink()
    third = prepare_reconstruction(workspace_root=ws, config=config)
    assert "chunk_0000.json" not in third["reused_outputs"]
    assert "lecture.json" not in third["reused_outputs"]
    assert not (ws / "responses/reconstruction/lecture.json").exists()


def test_reconstruction_input_change_invalidates_old_response_ids(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _timeline(ws, "定义内容")
    config = load_config()
    prepare_reconstruction(workspace_root=ws, config=config)
    old_req = json.loads((ws / "tasks/reconstruction/chunk_0000.request.json").read_text(encoding="utf-8"))
    atomic_write_json(ws / "responses/reconstruction/chunk_0000.json", _chunk_response(old_req["request_id"]))

    _timeline(ws, "定义内容已经改变")
    manifest = prepare_reconstruction(workspace_root=ws, config=config)
    new_req = json.loads((ws / "tasks/reconstruction/chunk_0000.request.json").read_text(encoding="utf-8"))
    assert new_req["request_id"] != old_req["request_id"]
    assert "chunk_0000.json" not in manifest["reused_outputs"]
    assert not (ws / "responses/reconstruction/chunk_0000.json").exists()


def test_review_prepare_reuses_each_reviewer_independently(tmp_path: Path) -> None:
    from video_to_notes.handoff.review import prepare_review

    ws = _workspace(tmp_path)
    atomic_write_json(ws / "lecture" / "lecture.json", {
        "schema_version": "1.0",
        "stage": "completion_draft",
        "metadata": {},
        "overview": {},
        "sections": [],
        "problems": [{
            "id": "P01",
            "title": "例题",
            "statement": {"content": "求证 A=B", "origin": "video", "evidence_ids": ["ev_0001"], "status": "confirmed"},
            "teacher_solution": {"content": "推导", "origin": "video", "evidence_ids": ["ev_0002"], "status": "confirmed"},
            "teacher_answer": {"content": "A=B", "origin": "video", "evidence_ids": ["ev_0003"], "status": "confirmed"},
        }],
        "supplements": [{
            "id": "sup_001", "target_id": "P01", "reason": "incomplete_explanation",
            "why_needed": "补全", "content": "完整推导", "origin": "supplement",
            "status": "probable", "type": "derived_solution", "math_review_status": "pending",
        }],
        "figures": [], "summary": [], "review": {"issues": []},
    })
    atomic_write_json(ws / "evidence" / "timeline.json", {"timeline": [
        {"id": "ev_0001", "start": 0, "end": 1, "frame_ids": [], "frames": [], "transcript_text": "求证", "status": "confirmed"},
        {"id": "ev_0002", "start": 1, "end": 2, "frame_ids": [], "frames": [], "transcript_text": "推导", "status": "confirmed"},
        {"id": "ev_0003", "start": 2, "end": 3, "frame_ids": [], "frames": [], "transcript_text": "答案", "status": "confirmed"},
    ]})
    config = load_config()
    first = prepare_review(workspace_root=ws, config=config)
    assert set(first["required_outputs"]) == {"factual.json", "math.json", "pedagogical.json"}

    for name in first["required_outputs"]:
        req = json.loads((ws / "tasks/review" / name.replace(".json", ".request.json")).read_text(encoding="utf-8"))
        payload = {"request_id": req["request_id"], "issues": []}
        if name == "math.json":
            payload["verified_supplements"] = ["sup_001"]
        atomic_write_json(ws / "responses/review" / name, payload)

    second = prepare_review(workspace_root=ws, config=config)
    assert set(second["reused_outputs"]) == {"factual.json", "math.json", "pedagogical.json"}

    # Corrupt only math; factual and pedagogical must remain reusable.
    bad = read_json(ws / "responses/review/math.json")
    bad["request_id"] = "stale"
    atomic_write_json(ws / "responses/review/math.json", bad)
    third = prepare_review(workspace_root=ws, config=config)
    assert set(third["reused_outputs"]) == {"factual.json", "pedagogical.json"}
    assert not (ws / "responses/review/math.json").exists()


def test_cli_accepts_performance_command() -> None:
    from video_to_notes.cli import build_parser
    args = build_parser().parse_args(["performance", "lesson.mp4"])
    assert args.command == "performance"
    assert args.reset is False
