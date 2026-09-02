from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

from .constants import STAGES
from .errors import StageError
from .receipt import invalidate_from, is_current, write_receipt
from .stages import StageContext
from .visual import run_visual_stage
from .transcription import run_transcription_stage
from .evidence import run_evidence_stage
from .reconstruction import run_reconstruction_stage
from .completion import run_completion_stage
from .review import run_review_stage
from .render import run_render_stage
from .audit import run_audit_stage
from .performance import record_stage


class Pipeline:
    IMPLEMENTED_HANDLERS: dict[str, Callable[[StageContext], None]] = {
        "visual": run_visual_stage,
        "transcription": run_transcription_stage,
        "evidence": run_evidence_stage,
        "reconstruction": run_reconstruction_stage,
        "completion": run_completion_stage,
        "review": run_review_stage,
        "render": run_render_stage,
        "audit": run_audit_stage,
    }

    def __init__(self, *, workspace_root: Path, config: dict[str, Any], logger: logging.Logger) -> None:
        self.workspace_root = workspace_root
        self.config = config
        self.logger = logger
        (workspace_root / "stages").mkdir(parents=True, exist_ok=True)

    def run(self, *, only_stage: str | None = None) -> None:
        target_stages = (only_stage,) if only_stage else STAGES
        for stage in target_stages:
            stage_cfg = self.config.get("stages", {}).get(stage, {})
            if not bool(stage_cfg.get("enabled", True)):
                self.logger.info("[%s] skipped by config", stage)
                continue

            if stage in {"reconstruction", "completion", "review"} and self.config.get("llm", {}).get("mode", "codex_handoff") == "codex_handoff":
                if is_current(self.workspace_root, self.config, stage):
                    self.logger.info("[%s] Stage Receipt current; reused", stage)
                else:
                    self.logger.info("[%s] requires Codex handoff", stage)
                return

            if is_current(self.workspace_root, self.config, stage):
                self.logger.info("[RECEIPT] %s reused", stage)
                record_stage(self.workspace_root, stage, 0.0, reused=True)
                continue

            handler = self.IMPLEMENTED_HANDLERS.get(stage)
            if handler is None:
                raise StageError(f"Unsupported stage: {stage}")
            invalidate_from(self.workspace_root, stage)
            self.logger.info("[%s] starting", stage)
            started = time.perf_counter()
            try:
                handler(StageContext(stage=stage, workspace_root=self.workspace_root, config=self.config, logger=self.logger))
                write_receipt(self.workspace_root, self.config, stage)
                record_stage(self.workspace_root, stage, time.perf_counter() - started, reused=False)
                self.logger.info("[%s] done", stage)
            except Exception as exc:
                self.logger.exception("[%s] failed: %s", stage, exc)
                if self.config.get("pipeline", {}).get("stop_on_failure", True):
                    raise StageError(f"Stage failed: {stage}") from exc
