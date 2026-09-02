from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable

from .errors import StageError
from .handoff import apply_completion, apply_reconstruction, apply_review, prepare_completion, prepare_reconstruction, prepare_review
from .pipeline import Pipeline
from .receipt import invalidate_from, is_current, write_receipt, request_id
from .stages import StageContext
from .util import atomic_write_json, read_json
from .workspace import Workspace
from .handoff.common import response_is_ready
from .performance import write_performance_report

HANDOFF_STAGES = ("reconstruction", "completion", "review")
DETERMINISTIC_PREFIX = ("visual", "transcription", "evidence")
DETERMINISTIC_SUFFIX = ("render", "audit")


@dataclass(frozen=True)
class WorkflowResult:
    status: str
    workspace: str
    stage: str | None = None
    task_dir: str | None = None
    response_dir: str | None = None
    required_outputs: list[str] | None = None
    missing_outputs: list[str] | None = None
    required_models: list[str] | None = None
    latex: str | None = None
    pdf: str | None = None
    audit_report: str | None = None
    audit_verdict: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


class CodexWorkflow:
    def __init__(self, *, workspace: Workspace, config: dict[str, Any], logger: Any) -> None:
        self.ws = workspace
        self.config = config
        self.logger = logger

    def advance(self) -> WorkflowResult:
        for stage in DETERMINISTIC_PREFIX:
            self._run_deterministic(stage)
        for stage in HANDOFF_STAGES:
            result = self._advance_handoff(stage)
            if result is not None:
                self._write_report(result)
                write_performance_report(self.ws.root)
                return result
        for stage in DETERMINISTIC_SUFFIX:
            self._run_deterministic(stage)
        result = self._terminal_result()
        self._write_report(result)
        write_performance_report(self.ws.root)
        return result

    def _run_deterministic(self, stage: str) -> None:
        Pipeline(workspace_root=self.ws.root, config=self.config, logger=self.logger).run(only_stage=stage)

    def _advance_handoff(self, stage: str) -> WorkflowResult | None:
        if is_current(self.ws.root, self.config, stage):
            return None
        manifest_path = self.ws.root / "tasks" / stage / "manifest.json"
        current_input_id = request_id(self.ws.root, self.config, stage)
        # Review is a cumulative multi-phase handoff (factual -> Medium -> High -> pedagogical).
        # Re-preparing it is idempotent and preserves exact valid responses while exposing
        # only the next required request files.
        if stage == "review":
            self._prepare_handoff(stage)
        else:
            needs_prepare = not manifest_path.exists()
            if not needs_prepare:
                try:
                    existing_manifest = read_json(manifest_path)
                    needs_prepare = not isinstance(existing_manifest, dict) or str(existing_manifest.get("input_id", "")) != current_input_id
                except Exception:
                    needs_prepare = True
            if needs_prepare:
                self._prepare_handoff(stage)
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict):
            raise StageError(f"非法 handoff manifest: {manifest_path}")
        required = [str(x) for x in manifest.get("required_outputs", [])]
        response_dir = self.ws.root / "responses" / stage
        missing = [name for name in required if not response_is_ready(self.ws.root, stage, manifest, name)]
        if missing:
            return WorkflowResult(
                status="CODEX_TASK_REQUIRED",
                workspace=str(self.ws.root), stage=stage,
                task_dir=str(self.ws.root / "tasks" / stage), response_dir=str(response_dir),
                required_outputs=required, missing_outputs=missing,
                required_models=self._required_models(stage, manifest, missing),
                message="Codex must complete the prepared request JSON files and invoke the same workflow command again.",
            )
        self._apply_handoff(stage)
        return None

    def _prepare_handoff(self, stage: str) -> None:
        prepare: dict[str, Callable[..., dict[str, Any]]] = {
            "reconstruction": prepare_reconstruction,
            "completion": prepare_completion,
            "review": prepare_review,
        }
        invalidate_from(self.ws.root, stage)
        manifest = prepare[stage](workspace_root=self.ws.root, config=self.config)
        self.logger.info("[workflow] prepared %s handoff (%d outputs)", stage, len(manifest.get("required_outputs", [])))

    def _apply_handoff(self, stage: str) -> None:
        self.logger.info("[workflow] applying %s handoff", stage)
        if stage == "reconstruction":
            apply_reconstruction(workspace_root=self.ws.root, config=self.config, ctx=StageContext(stage=stage, workspace_root=self.ws.root, config=self.config, logger=self.logger))
        elif stage == "completion":
            apply_completion(workspace_root=self.ws.root, config=self.config)
        elif stage == "review":
            apply_review(workspace_root=self.ws.root, config=self.config)
        else:
            raise StageError(f"Unsupported workflow handoff stage: {stage}")
        write_receipt(self.ws.root, self.config, stage)
        self.logger.info("[workflow] %s handoff applied", stage)

    def _required_models(self, stage: str, manifest: dict[str, Any], outputs: list[str]) -> list[str]:
        models: list[str] = []
        requests = manifest.get("requests", {}) if isinstance(manifest, dict) else {}
        for output in outputs:
            entry = requests.get(output, {}) if isinstance(requests, dict) else {}
            request_file = str(entry.get("request_file", "")) if isinstance(entry, dict) else ""
            if not request_file:
                request_file = output.replace(".json", ".request.json")
            path = self.ws.root / "tasks" / stage / request_file
            if not path.exists():
                continue
            data = read_json(path)
            model = str(data.get("required_model", "")) if isinstance(data, dict) else ""
            if model and model not in models:
                models.append(model)
        return models

    def _terminal_result(self) -> WorkflowResult:
        quality_path = self.ws.reports / "quality_report.json"
        verdict = None
        if quality_path.exists():
            quality = read_json(quality_path)
            if isinstance(quality, dict):
                verdict = str(quality.get("verdict", "")) or None
        pdf = self.ws.output / "lecture.pdf"
        tex = self.ws.latex / "lecture.tex"
        if not tex.exists() or not pdf.exists() or pdf.stat().st_size == 0:
            raise StageError("workflow reached terminal stages but LaTeX/PDF output is missing.")
        return WorkflowResult(
            status="WORKFLOW_COMPLETE" if verdict in {"PASS", "PASS_WITH_NOTES"} else "WORKFLOW_COMPLETE_REVIEW_REQUIRED",
            workspace=str(self.ws.root), latex=str(tex), pdf=str(pdf), audit_report=str(self.ws.reports / "quality_report.md"), audit_verdict=verdict,
            message="LaTeX/PDF generated and audit completed.",
        )

    def _write_report(self, result: WorkflowResult) -> None:
        atomic_write_json(self.ws.reports / "workflow_report.json", {"schema_version": "1.2", **result.to_dict()})


def format_workflow_result(result: WorkflowResult) -> str:
    lines = ["=== VIDEO_TO_NOTES_WORKFLOW ===", f"STATUS: {result.status}", f"WORKSPACE: {result.workspace}"]
    for key, label in (("stage","STAGE"),("task_dir","TASK_DIR"),("response_dir","RESPONSE_DIR"),("latex","LATEX"),("pdf","PDF"),("audit_report","AUDIT_REPORT"),("audit_verdict","AUDIT")):
        value = getattr(result, key)
        if value is not None:
            lines.append(f"{label}: {value}")
    if result.required_models:
        lines.append("REQUIRED_MODELS: " + ", ".join(result.required_models))
    if result.missing_outputs:
        lines.append("MISSING_OUTPUTS: " + ", ".join(result.missing_outputs))
    if result.message:
        lines.append(f"MESSAGE: {result.message}")
    lines.append("=== END_VIDEO_TO_NOTES_WORKFLOW ===")
    return "\n".join(lines)
