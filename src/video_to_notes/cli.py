from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .constants import STAGES
from .errors import VideoToNotesError
from .logging_utils import setup_logging
from .pipeline import Pipeline
from .workspace import create_workspace, resolve_workspace_root, Workspace
from .receipt import invalidate_from, is_current, receipt_path, write_receipt
from .workflow import CodexWorkflow, format_workflow_result
from .handoff import (
    prepare_reconstruction, apply_reconstruction,
    prepare_completion, apply_completion,
    prepare_review, apply_review,
)
from .stages import StageContext
from .performance import write_performance_report, reset_performance
from .handoff.common import response_is_ready


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-to-notes",
        description="Visual-first course video reconstruction pipeline.",
    )
    parser.add_argument(
        "--config",
        help="YAML configuration file. Defaults to config/default.yaml when present.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create or reuse a lesson workspace.")
    p_init.add_argument("video")

    p_run = sub.add_parser("run", help="Run all currently implemented stages.")
    p_run.add_argument("video")

    p_workflow = sub.add_parser(
        "workflow",
        help="Advance the resumable one-shot Codex workflow until the next semantic task or final LaTeX/PDF.",
    )
    p_workflow.add_argument("video")

    p_visual = sub.add_parser(
        "visual",
        help="Run only Sprint 2 Visual Reconstruction.",
    )
    p_visual.add_argument("video")

    p_transcribe = sub.add_parser(
        "transcribe",
        help="Run only Sprint 3 Audio / Whisper transcription.",
    )
    p_transcribe.add_argument("video")

    p_evidence = sub.add_parser(
        "evidence",
        help="Run only Sprint 4 Multimodal Evidence Timeline.",
    )
    p_evidence.add_argument("video")

    p_reconstruct = sub.add_parser(
        "reconstruct",
        help="Sprint 5 Course Reconstruction (Codex handoff by default).",
    )
    reconstruct_sub = p_reconstruct.add_subparsers(dest="action", required=True)
    for action in ("prepare", "apply", "api"):
        sp = reconstruct_sub.add_parser(action)
        sp.add_argument("video")

    p_complete = sub.add_parser(
        "complete",
        help="Sprint 6 Pedagogical Completion (Codex handoff by default).",
    )
    complete_sub = p_complete.add_subparsers(dest="action", required=True)
    for action in ("prepare", "apply", "api"):
        sp = complete_sub.add_parser(action)
        sp.add_argument("video")

    p_review = sub.add_parser(
        "review",
        help="Sprint 7 Review Layer (Codex handoff by default).",
    )
    review_sub = p_review.add_subparsers(dest="action", required=True)
    for action in ("prepare", "apply", "api"):
        sp = review_sub.add_parser(action)
        sp.add_argument("video")

    p_render = sub.add_parser(
        "render",
        help="Run only Sprint 8 LaTeX/PDF Rendering.",
    )
    p_render.add_argument("video")

    p_audit = sub.add_parser(
        "audit",
        help="Run only Sprint 9 Quality Audit.",
    )
    p_audit.add_argument("video")

    p_tasks = sub.add_parser(
        "codex-tasks",
        help="Show Codex handoff task/response status.",
    )
    p_tasks.add_argument("video")

    p_status = sub.add_parser("status", help="Show stage status.")
    p_status.add_argument("video")

    p_perf = sub.add_parser("performance", help="Show or reset performance measurements for a lesson workspace.")
    p_perf.add_argument("video")
    p_perf.add_argument("--reset", action="store_true", help="Clear accumulated performance measurements.")

    p_reset = sub.add_parser("reset", help="Reset stage state/cache.")
    p_reset.add_argument("video")
    group = p_reset.add_mutually_exclusive_group(required=True)
    group.add_argument("--stage", choices=STAGES)
    group.add_argument("--all", action="store_true")
    p_reset.add_argument(
        "--downstream",
        action="store_true",
        help="Also reset every stage after --stage.",
    )

    return parser


def _workspace_root_from_config(config: dict) -> Path:
    return Path(config["project"]["workspace_root"]).expanduser().resolve()


def _resolve_existing_workspace(video: Path, config: dict) -> Workspace:
    root = resolve_workspace_root(
        video.expanduser().resolve(),
        _workspace_root_from_config(config),
    )
    return Workspace.from_root(root)


def _prepare(video: Path, config: dict) -> Workspace:
    ws = create_workspace(
        video,
        workspace_root=_workspace_root_from_config(config),
        copy_source_video=bool(config["project"].get("copy_source_video", False)),
    )
    return ws


def _logger(ws: Workspace, config: dict):
    return setup_logging(
        log_dir=ws.logs,
        level=config["logging"].get("level", "INFO"),
        console=bool(config["logging"].get("console", True)),
        file=bool(config["logging"].get("file", True)),
    )


def cmd_init(video: Path, config: dict) -> int:
    ws = _prepare(video, config)
    print(f"Workspace: {ws.root}")
    print("Initialized.")
    return 0


def cmd_run(video: Path, config: dict, *, only_stage: str | None = None) -> int:
    ws = _prepare(video, config)
    logger = _logger(ws, config)

    logger.info("Workspace: %s", ws.root)
    pipeline = Pipeline(
        workspace_root=ws.root,
        config=config,
        logger=logger,
    )
    pipeline.run(only_stage=only_stage)
    logger.info("Pipeline finished.")
    return 0



def cmd_workflow(video: Path, config: dict) -> int:
    ws = _prepare(video, config)
    logger = _logger(ws, config)
    logger.info("Workspace: %s", ws.root)
    workflow = CodexWorkflow(workspace=ws, config=config, logger=logger)
    result = workflow.advance()
    print(format_workflow_result(result))
    return 0


def cmd_handoff(video: Path, config: dict, *, stage: str, action: str) -> int:
    if action == "api":
        from copy import deepcopy
        api_config = deepcopy(config)
        api_config.setdefault("llm", {})["mode"] = "api"
        return cmd_run(video, api_config, only_stage=stage)

    ws = _prepare(video, config)
    logger = _logger(ws, config)
    logger.info("Workspace: %s", ws.root)
    if action == "prepare":
        if stage == "reconstruction":
            manifest = prepare_reconstruction(workspace_root=ws.root, config=config)
        elif stage == "completion":
            manifest = prepare_completion(workspace_root=ws.root, config=config)
        elif stage == "review":
            manifest = prepare_review(workspace_root=ws.root, config=config)
        else:
            raise VideoToNotesError(f"不支持 handoff stage: {stage}")
        invalidate_from(ws.root, stage)
        print(f"Prepared Codex task: {ws.root / 'tasks' / stage}")
        print(f"Expected responses: {ws.root / 'responses' / stage}")
        print(f"Required outputs: {', '.join(manifest.get('required_outputs', []))}")
        return 0

    if action == "apply":
        try:
            if stage == "reconstruction":
                report = apply_reconstruction(
                    workspace_root=ws.root,
                    config=config,
                    ctx=StageContext(stage=stage, workspace_root=ws.root, config=config, logger=logger),
                )
            elif stage == "completion":
                report = apply_completion(workspace_root=ws.root, config=config)
            elif stage == "review":
                report = apply_review(workspace_root=ws.root, config=config)
            else:
                raise VideoToNotesError(f"不支持 handoff stage: {stage}")
        except Exception:
            raise
        write_receipt(ws.root, config, stage)
        print(f"Applied Codex response: {stage}")
        print(f"Report: {ws.root / 'reports' / (stage + '_report.json')}")
        return 0

    raise VideoToNotesError(f"未知 handoff action: {action}")


def cmd_codex_tasks(video: Path, config: dict) -> int:
    ws = _resolve_existing_workspace(video, config)
    if not ws.root.exists():
        print(f"Workspace not initialized: {ws.root}", file=sys.stderr)
        return 2

    print(f"Workspace: {ws.root}")
    print("Codex handoff tasks:")
    for stage in ("reconstruction", "completion", "review"):
        task_dir = ws.root / "tasks" / stage
        response_dir = ws.root / "responses" / stage
        manifest_path = task_dir / "manifest.json"
        if not manifest_path.exists():
            print(f"  [WAIT ] {stage:<14} no prepared task")
            continue
        import json
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        required = list(manifest.get("required_outputs", []))
        missing = [name for name in required if not response_is_ready(ws.root, stage, manifest, name)]
        if is_current(ws.root, config, stage):
            label = "DONE"
        elif not missing:
            label = "READY"
        else:
            label = "TODO"
        print(f"  [{label:<5}] {stage:<14} responses {len(required)-len(missing)}/{len(required)}")
        for name in missing[:8]:
            print(f"          missing: {name}")
    return 0


def cmd_status(video: Path, config: dict) -> int:
    ws = _resolve_existing_workspace(video, config)
    if not ws.root.exists():
        print(f"Workspace not initialized: {ws.root}", file=sys.stderr)
        return 2
    print(f"Workspace: {ws.root}")
    print()
    width = max(len(x) for x in STAGES)
    for stage in STAGES:
        status = "done" if is_current(ws.root, config, stage) else ("stale" if receipt_path(ws.root, stage).exists() else "pending")
        print(f"{stage:<{width}}  {status}")
    return 0

def cmd_performance(video: Path, config: dict, *, reset: bool = False) -> int:
    ws = _resolve_existing_workspace(video, config)
    if not ws.root.exists():
        print(f"Workspace not initialized: {ws.root}", file=sys.stderr)
        return 2
    if reset:
        reset_performance(ws.root)
        print(f"Performance metrics reset: {ws.root}")
        return 0
    report = write_performance_report(ws.root)
    llm = report.get("llm", {})
    print(f"Workspace: {ws.root}")
    print(f"Report: {ws.reports / 'performance_report.md'}")
    print(f"LLM requests: {llm.get('requests_generated', 0)} generated / {llm.get('requests_reused', 0)} reused")
    print(f"Executed input characters: {llm.get('input_characters', 0)}")
    print(f"Avoided input characters: {llm.get('avoided_input_characters', 0)}")
    print(f"Image references executed: {llm.get('images_sent', 0)}")
    return 0


def cmd_reset(args: argparse.Namespace, video: Path, config: dict) -> int:
    ws = _resolve_existing_workspace(video, config)
    if not ws.root.exists():
        print(f"Workspace not initialized: {ws.root}", file=sys.stderr)
        return 2
    if args.all:
        invalidate_from(ws.root, STAGES[0])
        print("All stage receipts reset.")
        return 0
    assert args.stage is not None
    if args.downstream:
        invalidate_from(ws.root, args.stage)
        print(f"Reset {args.stage} and downstream stage receipts.")
    else:
        receipt_path(ws.root, args.stage).unlink(missing_ok=True)
        print(f"Reset stage receipt: {args.stage}")
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        video = Path(args.video)

        if args.command == "init":
            return cmd_init(video, config)
        if args.command == "run":
            return cmd_run(video, config)
        if args.command == "workflow":
            return cmd_workflow(video, config)
        if args.command == "visual":
            return cmd_run(video, config, only_stage="visual")
        if args.command == "transcribe":
            return cmd_run(video, config, only_stage="transcription")
        if args.command == "evidence":
            return cmd_run(video, config, only_stage="evidence")
        if args.command == "reconstruct":
            return cmd_handoff(video, config, stage="reconstruction", action=args.action)
        if args.command == "complete":
            return cmd_handoff(video, config, stage="completion", action=args.action)
        if args.command == "review":
            return cmd_handoff(video, config, stage="review", action=args.action)
        if args.command == "render":
            return cmd_run(video, config, only_stage="render")
        if args.command == "audit":
            return cmd_run(video, config, only_stage="audit")
        if args.command == "codex-tasks":
            return cmd_codex_tasks(video, config)
        if args.command == "status":
            return cmd_status(video, config)
        if args.command == "performance":
            return cmd_performance(video, config, reset=bool(args.reset))
        if args.command == "reset":
            return cmd_reset(args, video, config)

        parser.error("Unknown command.")
        return 2

    except VideoToNotesError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
