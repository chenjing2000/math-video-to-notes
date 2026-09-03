from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from .constants import STAGES
from .errors import StageError
from .util import atomic_write_json, read_json, sha256_file, stable_json_hash

STAGE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "visual": (),
    "transcription": (),
    "evidence": ("visual", "transcription"),
    "reconstruction": ("evidence",),
    "completion": ("reconstruction",),
    "review": ("completion",),
    "render": ("review",),
    "audit": ("render",),
}

STAGE_VERSIONS: dict[str, str] = {
    "visual": "3",
    "transcription": "2",
    "evidence": "2",
    "reconstruction": "4",
    "completion": "4",
    "review": "6",
    "render": "4",
    "audit": "4",
}

STAGE_OUTPUTS: dict[str, tuple[str, ...]] = {
    "visual": ("source/video_info.json", "visual/segments/segments.json", "visual/evidence_frames/evidence_frames.json", "reports/visual_report.json"),
    "transcription": ("transcript/transcript.json", "reports/transcription_report.json"),
    "evidence": ("evidence/timeline.json", "reports/evidence_report.json"),
    "reconstruction": ("lecture/reconstruction.json", "reports/reconstruction_report.json"),
    "completion": ("lecture/completed.json", "reports/completion_report.json"),
    "review": ("lecture/reviewed.json", "review/issues.json", "reports/review_report.json"),
    "render": ("latex/lecture.tex", "output/lecture.pdf", "reports/render_report.json"),
    "audit": ("reports/quality_report.json", "reports/quality_report.md"),
}


def receipt_path(workspace_root: Path, stage: str) -> Path:
    return workspace_root / "stages" / f"{stage}.receipt.json"


def _relevant_config(config: dict[str, Any], stage: str) -> dict[str, Any]:
    out: dict[str, Any] = {"stage": config.get("stages", {}).get(stage, {})}
    if stage == "visual":
        out.update(visual=config.get("visual", {}), tools=config.get("tools", {}))
    elif stage == "transcription":
        out.update(transcription=config.get("transcription", {}), tools=config.get("tools", {}))
    else:
        out[stage] = config.get(stage, {})
    if stage in {"reconstruction", "completion", "review"}:
        out["llm_mode"] = config.get("llm", {}).get("mode", "codex_handoff")
        out["model_routing"] = config.get("codex", {}).get("model_routing", {})
        try:
            from .config import resolve_resource_path
            value = config.get(stage, {}).get("prompts_file", "package:prompts.yaml")
            prompt_path = resolve_resource_path(value, default_name="prompts.yaml")
            if prompt_path.exists():
                out["prompt_sha256"] = sha256_file(prompt_path)
        except Exception:
            pass
    if stage == "render":
        try:
            from .config import resolve_resource_path
            value = config.get("render", {}).get("template", "package:lecture.tex.j2")
            template_path = resolve_resource_path(value, default_name="lecture.tex.j2")
            if template_path.exists():
                out["template_sha256"] = sha256_file(template_path)
        except Exception:
            pass
    return out


def _source_identity(workspace_root: Path) -> str:
    project = read_json(workspace_root / "project.json")
    return str(project.get("source", {}).get("sha256", ""))



LEGACY_PRIMARY_OUTPUT: dict[str, tuple[str, ...]] = {
    "visual": ("visual/evidence_frames/evidence_frames.json", "visual/segments/segments.json"),
    "transcription": ("transcript/transcript.json",),
    "evidence": ("evidence/timeline.json",),
    "reconstruction": ("lecture/reconstruction.json", "lecture/lecture.json"),
    "completion": ("lecture/completed.json", "lecture/lecture.json"),
    "review": ("lecture/reviewed.json", "lecture/lecture.json"),
    "render": ("reports/render_report.json", "output/lecture.pdf"),
}

def _legacy_dependency_id(workspace_root: Path, stage: str) -> str | None:
    hashes: list[tuple[str, str]] = []
    for rel in LEGACY_PRIMARY_OUTPUT.get(stage, ()): 
        path = workspace_root / rel
        if path.exists() and path.is_file():
            hashes.append((rel, sha256_file(path)))
    if not hashes:
        return None
    return "legacy:" + stable_json_hash(hashes)

def _dependency_ids(workspace_root: Path, stage: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for dep in STAGE_DEPENDENCIES.get(stage, ()):
        path = receipt_path(workspace_root, dep)
        if not path.exists():
            legacy = _legacy_dependency_id(workspace_root, dep)
            if legacy:
                result[dep] = legacy
                continue
            raise StageError(f"缺少上游 Stage Receipt/产物: {dep}")
        data = read_json(path)
        rid = str(data.get("receipt_id", ""))
        if not rid:
            raise StageError(f"非法上游 Stage Receipt: {path}")
        result[dep] = rid
    return result


def expected_identity(workspace_root: Path, config: dict[str, Any], stage: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "stage_version": STAGE_VERSIONS.get(stage, "1"),
        "source": _source_identity(workspace_root) if stage in {"visual", "transcription"} else None,
        "inputs": _dependency_ids(workspace_root, stage),
        "config_hash": stable_json_hash(_relevant_config(config, stage)),
    }


def request_id(workspace_root: Path, config: dict[str, Any], stage: str, extra: Any = None) -> str:
    identity = expected_identity(workspace_root, config, stage)
    if extra is not None:
        identity["request"] = extra
    return stable_json_hash(identity)


def write_receipt(workspace_root: Path, config: dict[str, Any], stage: str, *, status: str = "done", error: str | None = None) -> dict[str, Any]:
    if stage in {"reconstruction", "completion", "review"}:
        source = workspace_root / "lecture" / "lecture.json"
        target_name = {"reconstruction": "reconstruction.json", "completion": "completed.json", "review": "reviewed.json"}[stage]
        target = workspace_root / "lecture" / target_name
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    base = expected_identity(workspace_root, config, stage)
    outputs: dict[str, dict[str, Any]] = {}
    for rel in STAGE_OUTPUTS.get(stage, ()):
        path = workspace_root / rel
        if not path.exists():
            raise StageError(f"{stage} 缺少预期产物，不能写 receipt: {rel}")
        outputs[rel] = {"sha256": sha256_file(path), "size": path.stat().st_size}
    receipt: dict[str, Any] = {"schema": 1, **base, "status": status, "outputs": outputs}
    if error:
        receipt["error"] = error
    receipt["receipt_id"] = stable_json_hash({k: v for k, v in receipt.items() if k != "receipt_id"})
    atomic_write_json(receipt_path(workspace_root, stage), receipt)
    return receipt


def invalidate_from(workspace_root: Path, stage: str) -> None:
    try:
        start = STAGES.index(stage)
    except ValueError:
        return
    for name in STAGES[start:]:
        receipt_path(workspace_root, name).unlink(missing_ok=True)


def is_current(workspace_root: Path, config: dict[str, Any], stage: str) -> bool:
    path = receipt_path(workspace_root, stage)
    if not path.exists():
        return False
    try:
        data = read_json(path)
        if data.get("status") != "done":
            return False
        expected = expected_identity(workspace_root, config, stage)
        for key in ("stage", "stage_version", "source", "inputs", "config_hash"):
            if data.get(key) != expected.get(key):
                return False
        outputs = data.get("outputs", {})
        if not isinstance(outputs, dict):
            return False
        for rel, meta in outputs.items():
            p = workspace_root / rel
            if not p.exists() or not isinstance(meta, dict):
                return False
            if p.stat().st_size != int(meta.get("size", -1)):
                return False
            if sha256_file(p) != str(meta.get("sha256", "")):
                return False
        return True
    except Exception:
        return False


def receipt_id(workspace_root: Path, stage: str) -> str:
    data = read_json(receipt_path(workspace_root, stage))
    return str(data.get("receipt_id", ""))
