from pathlib import Path

from video_to_notes.config import load_config
from video_to_notes.receipt import is_current, request_id, write_receipt
from video_to_notes.util import atomic_write_json
from video_to_notes.workspace import create_workspace


def test_receipt_detects_output_mutation(tmp_path: Path):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"video")
    ws = create_workspace(video, workspace_root=tmp_path / "workspace")
    cfg = load_config()
    atomic_write_json(ws.source / "video_info.json", {"duration": 1})
    atomic_write_json(ws.visual / "segments" / "segments.json", {"segments": []})
    atomic_write_json(ws.visual / "evidence_frames" / "evidence_frames.json", {"frames": []})
    atomic_write_json(ws.reports / "visual_report.json", {"ok": True})
    write_receipt(ws.root, cfg, "visual")
    assert is_current(ws.root, cfg, "visual")
    atomic_write_json(ws.reports / "visual_report.json", {"ok": False})
    assert not is_current(ws.root, cfg, "visual")


def test_request_id_changes_with_legacy_upstream_artifact(tmp_path: Path):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"video")
    ws = create_workspace(video, workspace_root=tmp_path / "workspace")
    cfg = load_config()
    atomic_write_json(ws.evidence / "timeline.json", {"timeline": [{"id": "ev_1"}]})
    first = request_id(ws.root, cfg, "reconstruction")
    atomic_write_json(ws.evidence / "timeline.json", {"timeline": [{"id": "ev_2"}]})
    second = request_id(ws.root, cfg, "reconstruction")
    assert first != second


def test_same_name_different_video_gets_separate_workspace(tmp_path: Path):
    a = tmp_path / "a" / "lesson.mp4"
    b = tmp_path / "b" / "lesson.mp4"
    a.parent.mkdir(); b.parent.mkdir()
    a.write_bytes(b"aaa")
    b.write_bytes(b"bbb")
    root = tmp_path / "workspace"
    wa = create_workspace(a, workspace_root=root)
    wb = create_workspace(b, workspace_root=root)
    assert wa.root.name == "lesson"
    assert wb.root != wa.root
    assert wb.root.name.startswith("lesson__")


def test_same_source_reuses_workspace_identity(tmp_path: Path):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"same")
    root = tmp_path / "workspace"
    first = create_workspace(video, workspace_root=root)
    second = create_workspace(video, workspace_root=root)
    assert first.root == second.root
