import json
from pathlib import Path

from video_to_notes.config import load_config
from video_to_notes.handoff.review import apply_review, prepare_review
from video_to_notes.util import atomic_write_json, read_json


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace" / "lesson"
    for name in ("lecture", "evidence", "tasks/review", "responses/review", "reports", "review"):
        (ws / name).mkdir(parents=True, exist_ok=True)
    atomic_write_json(ws / "project.json", {"source": {"sha256": "abc"}})
    return ws


def test_medium_unresolved_escalates_only_target_to_high_and_high_unresolved_does_not_block(tmp_path: Path):
    ws = _workspace(tmp_path)
    teacher_partial = "老师只完成第一步；后续证明未完整呈现。"
    atomic_write_json(ws / "lecture/lecture.json", {
        "schema_version": "1.0", "stage": "completion_draft", "metadata": {}, "overview": {}, "sections": [],
        "problems": [{
            "id": "P01", "title": "例题",
            "statement": {"content": "求证 A=B", "origin": "video", "evidence_ids": ["ev_1"], "status": "confirmed"},
            "teacher_solution": {"content": teacher_partial, "origin": "video", "evidence_ids": ["ev_2"], "status": "confirmed"},
            "teacher_answer": {"content": "A=B", "origin": "video", "evidence_ids": ["ev_3"], "status": "confirmed"},
        }],
        "supplements": [{
            "id": "sup_001", "target_id": "P01", "type": "derived_solution",
            "reason": "incomplete_explanation", "why_needed": "补全", "content": "Terra 补充证明",
            "origin": "supplement", "status": "probable", "math_review_status": "pending",
        }],
        "figures": [], "summary": [], "review": {"issues": []},
    })
    atomic_write_json(ws / "evidence/timeline.json", {"timeline": [
        {"id": "ev_1", "start": 0, "end": 1, "frame_ids": [], "frames": [], "transcript_text": "求证", "status": "confirmed"},
        {"id": "ev_2", "start": 1, "end": 2, "frame_ids": [], "frames": [], "transcript_text": "第一步", "status": "confirmed"},
        {"id": "ev_3", "start": 2, "end": 3, "frame_ids": [], "frames": [], "transcript_text": "答案", "status": "confirmed"},
    ]})
    config = load_config()

    first = prepare_review(workspace_root=ws, config=config)
    factual = read_json(ws / "tasks/review/factual.request.json")
    atomic_write_json(ws / "responses/review/factual.json", {"request_id": factual["request_id"], "issues": []})

    second = prepare_review(workspace_root=ws, config=config)
    assert second["phase"] == "math_medium"
    medium_req = read_json(ws / "tasks/review/math_P01_medium.request.json")
    atomic_write_json(ws / "responses/review/math_P01_medium.json", {
        "request_id": medium_req["request_id"],
        "reviewed_solutions": [
            {"target_id": "P01.teacher_solution", "status": "verified"},
            {"target_id": "sup_001", "status": "unresolved", "content": "Medium 猜测不应保留"},
        ],
        "reviewed_answers": [{"target_id": "P01.teacher_answer", "status": "verified"}],
    })

    third = prepare_review(workspace_root=ws, config=config)
    assert third["phase"] == "math_high"
    high_req = read_json(ws / "tasks/review/math_P01_high.request.json")
    assert high_req["required_model"] == "sol-high"
    assert '"target_id": "sup_001"' in high_req["user"]
    # Resolved teacher solution/answer are context, not High review targets.
    assert '"target_id": "P01.teacher_solution"' not in high_req["user"]
    atomic_write_json(ws / "responses/review/math_P01_high.json", {
        "request_id": high_req["request_id"],
        "reviewed_solutions": [{"target_id": "sup_001", "status": "unresolved", "content": "High 猜测也不应保留"}],
        "reviewed_answers": [],
    })

    fourth = prepare_review(workspace_root=ws, config=config)
    assert fourth["phase"] == "pedagogical"
    ped = read_json(ws / "tasks/review/pedagogical.request.json")
    atomic_write_json(ws / "responses/review/pedagogical.json", {"request_id": ped["request_id"], "issues": []})
    fifth = prepare_review(workspace_root=ws, config=config)
    assert fifth["phase"] == "ready"

    report = apply_review(workspace_root=ws, config=config)
    lecture = read_json(ws / "lecture/lecture.json")
    problem = lecture["problems"][0]
    assert problem["math_review_unresolved"] is True
    assert problem["publication_solution"]["content"] == teacher_partial
    assert "Medium 猜测" not in json.dumps(lecture, ensure_ascii=False)
    assert "High 猜测" not in json.dumps(lecture, ensure_ascii=False)
    assert report["quality"]["complete"] is True
    assert report["quality"]["has_notes"] is True
    assert report["math_review"]["unresolved_targets"] == ["sup_001"]
    assert report["math_review"]["escalated_targets"] == ["sup_001"]
