from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .util import atomic_write_json, read_json

_METRICS_NAME = "performance_metrics.json"
_REPORT_JSON = "performance_report.json"
_REPORT_MD = "performance_report.md"
_IMAGE_RE = re.compile(r"[^\s\"']+\.(?:png|jpe?g|webp)", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reports(workspace_root: Path) -> Path:
    path = workspace_root / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _metrics_path(workspace_root: Path) -> Path:
    return _reports(workspace_root) / _METRICS_NAME


def _load(workspace_root: Path) -> dict[str, Any]:
    path = _metrics_path(workspace_root)
    if not path.exists():
        return {"schema_version": "1.0", "stage_events": [], "handoff_attempts": []}
    data = read_json(path)
    if not isinstance(data, dict):
        return {"schema_version": "1.0", "stage_events": [], "handoff_attempts": []}
    data.setdefault("schema_version", "1.0")
    data.setdefault("stage_events", [])
    data.setdefault("handoff_attempts", [])
    return data


def _save(workspace_root: Path, data: dict[str, Any]) -> None:
    """Persist raw metrics only; reports are generated on demand or at workflow boundaries."""
    atomic_write_json(_metrics_path(workspace_root), data)


def reset_performance(workspace_root: Path) -> None:
    reports = _reports(workspace_root)
    for name in (_METRICS_NAME, _REPORT_JSON, _REPORT_MD):
        (reports / name).unlink(missing_ok=True)


def record_stage(workspace_root: Path, stage: str, duration_seconds: float, *, reused: bool = False) -> None:
    data = _load(workspace_root)
    data["stage_events"].append({
        "at": _now(),
        "stage": stage,
        "duration_seconds": round(max(0.0, float(duration_seconds)), 6),
        "reused": bool(reused),
    })
    _save(workspace_root, data)


def request_metrics(request: dict[str, Any]) -> dict[str, Any]:
    system = str(request.get("system", ""))
    user = str(request.get("user", ""))
    user_template = str(request.get("user_template", ""))
    text = system + user + user_template
    raw = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    image_refs = sorted(set(_IMAGE_RE.findall(text)))
    return {
        "input_characters": len(text),
        "request_bytes": len(raw.encode("utf-8")),
        "images_sent": len(image_refs),
        "image_refs": image_refs,
    }


def record_handoff_prepare(
    workspace_root: Path,
    stage: str,
    *,
    input_id: str,
    requests: dict[str, dict[str, Any]],
    reused_outputs: set[str] | None = None,
    warning_thresholds: dict[str, Any] | None = None,
) -> None:
    reused_outputs = reused_outputs or set()
    warning_thresholds = warning_thresholds or {}
    data = _load(workspace_root)
    entry: dict[str, Any] = {
        "stage": stage,
        "input_id": input_id,
        "prepared_at": _now(),
        "applied_at": None,
        "requests": {},
    }
    for output_name, request in requests.items():
        metrics = request_metrics(request)
        task_type = str(request.get("task_type", ""))
        threshold_key = {
            "reconstruction_chunk": "reconstruction",
            "reconstruction_merge": "reconstruction",
            "completion_chunk": "completion",
            "completion_merge": "completion",
            "review_factual": "factual_review",
            "review_math": "math_review",
            "review_math_high": "math_review",
            "review_pedagogical": "pedagogical_review",
        }.get(task_type, stage)
        threshold = int(warning_thresholds.get(threshold_key, 0) or 0)
        entry["requests"][output_name] = {
            "request_id": str(request.get("request_id", "")),
            "task_type": task_type,
            "model": str(request.get("required_model", "")) or None,
            "input_characters": metrics["input_characters"],
            "request_bytes": metrics["request_bytes"],
            "images_sent": metrics["images_sent"],
            "warning_threshold_chars": threshold or None,
            "oversized": bool(threshold and metrics["input_characters"] > threshold),
            "reused": output_name in reused_outputs,
            "output_characters": None,
        }
    data["handoff_attempts"].append(entry)
    _save(workspace_root, data)


def record_handoff_apply(workspace_root: Path, stage: str, response_dir: Path) -> None:
    data = _load(workspace_root)
    attempts = [x for x in data.get("handoff_attempts", []) if isinstance(x, dict) and x.get("stage") == stage and not x.get("applied_at")]
    if not attempts:
        return
    attempt = attempts[-1]
    attempt["applied_at"] = _now()
    for output_name, info in attempt.get("requests", {}).items():
        path = response_dir / output_name
        if path.exists():
            try:
                raw = path.read_text(encoding="utf-8")
                info["output_characters"] = len(raw)
            except Exception:
                pass
    _save(workspace_root, data)


def _stage_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        stage = str(event.get("stage", ""))
        if not stage:
            continue
        item = summary.setdefault(stage, {"runs": 0, "reuses": 0, "duration_seconds": 0.0})
        if event.get("reused"):
            item["reuses"] += 1
        else:
            item["runs"] += 1
        item["duration_seconds"] += float(event.get("duration_seconds", 0.0) or 0.0)
    for item in summary.values():
        item["duration_seconds"] = round(item["duration_seconds"], 3)
    return summary


def build_performance_report(workspace_root: Path) -> dict[str, Any]:
    data = _load(workspace_root)
    stage_summary = _stage_summary(data.get("stage_events", []))
    requests_generated = 0
    requests_reused = 0
    input_chars_total = 0
    avoided_input_chars = 0
    output_chars_total = 0
    images_total = 0
    avoided_images = 0
    by_stage: dict[str, Any] = {}
    largest: list[dict[str, Any]] = []
    packet_warnings: list[dict[str, Any]] = []
    math_medium_request_ids: set[str] = set()
    math_high_request_ids: set[str] = set()

    for attempt in data.get("handoff_attempts", []):
        if not isinstance(attempt, dict):
            continue
        stage = str(attempt.get("stage", ""))
        stage_item = by_stage.setdefault(stage, {
            "request_count": 0,
            "reused_requests": 0,
            "input_characters": 0,
            "output_characters": 0,
            "images_sent": 0,
            "avoided_input_characters": 0,
            "avoided_images": 0,
            "wall_seconds": 0.0,
        })
        wall = _iso_seconds(attempt.get("prepared_at"), attempt.get("applied_at"))
        if wall is not None:
            stage_item["wall_seconds"] += wall
        for output_name, info in attempt.get("requests", {}).items():
            if not isinstance(info, dict):
                continue
            requests_generated += 1
            stage_item["request_count"] += 1
            chars = int(info.get("input_characters", 0) or 0)
            imgs = int(info.get("images_sent", 0) or 0)
            out_chars = int(info.get("output_characters", 0) or 0)
            reused = bool(info.get("reused"))
            task_type = str(info.get("task_type", ""))
            rid = str(info.get("request_id", ""))
            if task_type == "review_math" and rid:
                math_medium_request_ids.add(rid)
            elif task_type == "review_math_high" and rid:
                math_high_request_ids.add(rid)
            if reused:
                requests_reused += 1
                stage_item["reused_requests"] += 1
                avoided_input_chars += chars
                avoided_images += imgs
                stage_item["avoided_input_characters"] += chars
                stage_item["avoided_images"] += imgs
            else:
                input_chars_total += chars
                images_total += imgs
                stage_item["input_characters"] += chars
                stage_item["images_sent"] += imgs
            output_chars_total += out_chars
            stage_item["output_characters"] += out_chars
            largest.append({
                "stage": stage,
                "output": output_name,
                "request_id": info.get("request_id"),
                "input_characters": chars,
                "images_sent": imgs,
                "reused": reused,
            })
            if info.get("oversized"):
                packet_warnings.append({
                    "stage": stage,
                    "output": output_name,
                    "input_characters": chars,
                    "warning_threshold_chars": info.get("warning_threshold_chars"),
                })

    largest.sort(key=lambda x: int(x.get("input_characters", 0)), reverse=True)
    for item in by_stage.values():
        item["wall_seconds"] = round(float(item.get("wall_seconds", 0.0)), 3)
    report = {
        "schema_version": "1.0",
        "workspace": str(workspace_root),
        "stage_summary": stage_summary,
        "llm": {
            "by_stage": by_stage,
            "requests_generated": requests_generated,
            "requests_executed": requests_generated - requests_reused,
            "requests_reused": requests_reused,
            "input_characters": input_chars_total,
            "output_characters": output_chars_total,
            "images_sent": images_total,
            "avoided_input_characters": avoided_input_chars,
            "avoided_images": avoided_images,
            "largest_requests": largest[:10],
            "packet_warnings": packet_warnings,
            "math_medium_requests": len(math_medium_request_ids),
            "math_high_requests": len(math_high_request_ids),
            "math_high_escalation_rate": round(len(math_high_request_ids) / len(math_medium_request_ids), 4) if math_medium_request_ids else 0.0,
        },
    }
    return report


def _iso_seconds(start: Any, end: Any) -> float | None:
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(str(start))
        b = datetime.fromisoformat(str(end))
        return max(0.0, (b - a).total_seconds())
    except Exception:
        return None


def _format_seconds(value: Any) -> str:
    try:
        seconds = float(value)
    except Exception:
        return "-"
    return f"{seconds:.1f} s"


def render_performance_markdown(report: dict[str, Any]) -> str:
    lines = ["# Performance Report", "", "## Stage time", "", "| Stage | Runs | Reuses | Time |", "|---|---:|---:|---:|"]
    for stage, item in report.get("stage_summary", {}).items():
        lines.append(f"| {stage} | {item.get('runs', 0)} | {item.get('reuses', 0)} | {_format_seconds(item.get('duration_seconds', 0))} |")
    llm = report.get("llm", {})
    lines += [
        "", "## LLM workload", "",
        f"- Requests generated: {llm.get('requests_generated', 0)}",
        f"- Requests executed: {llm.get('requests_executed', 0)}",
        f"- Requests reused: {llm.get('requests_reused', 0)}",
        f"- Sol Medium math requests: {llm.get('math_medium_requests', 0)}",
        f"- Sol High escalations: {llm.get('math_high_requests', 0)}",
        f"- Sol High escalation rate: {float(llm.get('math_high_escalation_rate', 0.0)):.1%}",
        f"- Input characters executed: {llm.get('input_characters', 0)}",
        f"- Output characters observed: {llm.get('output_characters', 0)}",
        f"- Images referenced by executed requests: {llm.get('images_sent', 0)}",
        f"- Avoided input characters by reuse: {llm.get('avoided_input_characters', 0)}",
        f"- Avoided image references by reuse: {llm.get('avoided_images', 0)}",
        "", "### By stage", "",
        "| Stage | Requests | Reused | Input chars | Images | Wall time* |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for stage, item in llm.get("by_stage", {}).items():
        lines.append(f"| {stage} | {item.get('request_count', 0)} | {item.get('reused_requests', 0)} | {item.get('input_characters', 0)} | {item.get('images_sent', 0)} | {_format_seconds(item.get('wall_seconds', 0))} |")
    lines += ["", "*LLM wall time includes the interval between handoff preparation and apply; it may include human/Codex scheduling delay.*", "", "## Largest requests", "",
        "| Stage | Output | Input chars | Images | Reused |",
        "|---|---|---:|---:|---|",
    ]
    for item in llm.get("largest_requests", []):
        lines.append(f"| {item.get('stage')} | {item.get('output')} | {item.get('input_characters', 0)} | {item.get('images_sent', 0)} | {'yes' if item.get('reused') else 'no'} |")
    warnings = llm.get("packet_warnings", [])
    if warnings:
        lines += ["", "## Packet size warnings", ""]
        for item in warnings:
            lines.append(f"- {item.get('stage')} / {item.get('output')}: {item.get('input_characters')} chars > warning threshold {item.get('warning_threshold_chars')}")
    lines.append("")
    return "\n".join(lines)


def write_performance_report(workspace_root: Path) -> dict[str, Any]:
    report = build_performance_report(workspace_root)
    reports = _reports(workspace_root)
    atomic_write_json(reports / _REPORT_JSON, report)
    (reports / _REPORT_MD).write_text(render_performance_markdown(report), encoding="utf-8")
    return report
