from __future__ import annotations

import logging
from pathlib import Path

from video_to_notes.cli import build_parser
from video_to_notes.util import atomic_write_json
from video_to_notes.workflow import CodexWorkflow, format_workflow_result
from video_to_notes.workspace import Workspace


def _workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / "lesson"
    ws = Workspace.from_root(root)
    for path in (
        ws.source, ws.visual, ws.transcript, ws.evidence, ws.lecture,
        ws.review, ws.images, ws.latex, ws.output, ws.reports, ws.logs, ws.stages,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return ws


def _workflow(ws: Workspace) -> CodexWorkflow:
    return CodexWorkflow(
        workspace=ws,
        config={},
        logger=logging.getLogger("test-workflow"),
    )


def test_cli_accepts_workflow_command() -> None:
    args = build_parser().parse_args(["workflow", r"E:\videos\lesson.mp4"])
    assert args.command == "workflow"
    assert args.video.endswith("lesson.mp4")


def test_workflow_prepares_and_reports_codex_task(tmp_path: Path, monkeypatch) -> None:
    ws = _workspace(tmp_path)
    workflow = _workflow(ws)
    monkeypatch.setattr(workflow, "_run_deterministic", lambda stage: None)
    monkeypatch.setattr("video_to_notes.workflow.request_id", lambda root, config, stage: f"input-{stage}")

    def fake_prepare(stage: str) -> None:
        task = ws.root / "tasks" / stage
        response = ws.root / "responses" / stage
        task.mkdir(parents=True, exist_ok=True)
        response.mkdir(parents=True, exist_ok=True)
        atomic_write_json(task / "manifest.json", {
            "input_id": f"input-{stage}",
            "required_outputs": ["chunk_0000.json", "lecture.json"],
            "requests": {
                "chunk_0000.json": {"request_id": "chunk-rid"},
                "lecture.json": {"request_id": "merge-rid"},
            },
        })
        atomic_write_json(task / "chunk_0000.request.json", {
            "request_id": "chunk-rid", "required_model": "terra",
        })

    monkeypatch.setattr(workflow, "_prepare_handoff", fake_prepare)
    result = workflow.advance()

    assert result.status == "CODEX_TASK_REQUIRED"
    assert result.stage == "reconstruction"
    assert result.required_models == ["terra"]
    assert result.missing_outputs == ["chunk_0000.json", "lecture.json"]
    assert (ws.reports / "workflow_report.json").exists()
    rendered = format_workflow_result(result)
    assert "STATUS: CODEX_TASK_REQUIRED" in rendered
    assert "REQUIRED_MODELS: terra" in rendered


def test_workflow_applies_ready_handoff_then_advances(tmp_path: Path, monkeypatch) -> None:
    ws = _workspace(tmp_path)
    workflow = _workflow(ws)
    monkeypatch.setattr(workflow, "_run_deterministic", lambda stage: None)
    monkeypatch.setattr("video_to_notes.workflow.request_id", lambda root, config, stage: f"input-{stage}")

    # Reconstruction is prepared and complete, so the controller should apply it.
    task = ws.root / "tasks" / "reconstruction"
    response = ws.root / "responses" / "reconstruction"
    task.mkdir(parents=True, exist_ok=True)
    response.mkdir(parents=True, exist_ok=True)
    atomic_write_json(task / "manifest.json", {
        "input_id": "input-reconstruction",
        "required_outputs": ["lecture.json"],
        "requests": {"lecture.json": {"request_id": "recon-merge"}},
    })
    atomic_write_json(task / "merge.request.json", {"request_id": "recon-merge", "required_model": "terra"})
    atomic_write_json(response / "lecture.json", {"request_id": "recon-merge", "ok": True})

    applied: list[str] = []

    def fake_apply(stage: str) -> None:
        applied.append(stage)

    def fake_prepare(stage: str) -> None:
        task_dir = ws.root / "tasks" / stage
        response_dir = ws.root / "responses" / stage
        task_dir.mkdir(parents=True, exist_ok=True)
        response_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(task_dir / "manifest.json", {"required_outputs": ["completion.json"]})
        atomic_write_json(task_dir / "merge.request.json", {"required_model": "terra"})

    monkeypatch.setattr(workflow, "_apply_handoff", fake_apply)
    monkeypatch.setattr(workflow, "_prepare_handoff", fake_prepare)

    result = workflow.advance()
    assert applied == ["reconstruction"]
    assert result.status == "CODEX_TASK_REQUIRED"
    assert result.stage == "completion"


def test_workflow_terminal_result_exposes_artifacts(tmp_path: Path, monkeypatch) -> None:
    ws = _workspace(tmp_path)
    workflow = _workflow(ws)
    monkeypatch.setattr("video_to_notes.workflow.is_current", lambda root, config, stage: stage in {"reconstruction", "completion", "review"})

    def fake_run(stage: str) -> None:
        if stage == "render":
            ws.latex.mkdir(parents=True, exist_ok=True)
            ws.output.mkdir(parents=True, exist_ok=True)
            (ws.latex / "lecture.tex").write_text("\\documentclass{article}", encoding="utf-8")
            (ws.output / "lecture.pdf").write_bytes(b"%PDF-1.4\n")
        elif stage == "audit":
            atomic_write_json(ws.reports / "quality_report.json", {"verdict": "PASS"})
            (ws.reports / "quality_report.md").write_text("PASS", encoding="utf-8")

    monkeypatch.setattr(workflow, "_run_deterministic", fake_run)
    result = workflow.advance()

    assert result.status == "WORKFLOW_COMPLETE"
    assert result.audit_verdict == "PASS"
    assert result.pdf and result.pdf.endswith("lecture.pdf")
    assert result.latex and result.latex.endswith("lecture.tex")


def test_review_required_is_terminal_but_not_final_quality(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    workflow = _workflow(ws)
    (ws.latex / "lecture.tex").write_text("tex", encoding="utf-8")
    (ws.output / "lecture.pdf").write_bytes(b"pdf")
    atomic_write_json(ws.reports / "quality_report.json", {"verdict": "REVIEW_REQUIRED"})
    result = workflow._terminal_result()
    assert result.status == "WORKFLOW_COMPLETE_REVIEW_REQUIRED"
    assert result.audit_verdict == "REVIEW_REQUIRED"


def test_pass_with_notes_is_terminal_complete(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    workflow = _workflow(ws)
    (ws.latex / "lecture.tex").write_text("tex", encoding="utf-8")
    (ws.output / "lecture.pdf").write_bytes(b"pdf")
    atomic_write_json(ws.reports / "quality_report.json", {"verdict": "PASS_WITH_NOTES"})
    result = workflow._terminal_result()
    assert result.status == "WORKFLOW_COMPLETE"
    assert result.audit_verdict == "PASS_WITH_NOTES"
