from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..errors import StageError
from ..stages import StageContext
from ..util import atomic_write_json, read_json


def _read_report(root: Path, name: str) -> dict[str, Any]:
    path = root / "reports" / name
    if not path.exists():
        raise StageError(f"缺少阶段报告: {path}")
    data = read_json(path)
    if not isinstance(data, dict):
        raise StageError(f"非法阶段报告: {path}")
    return data


def _quality(report: dict[str, Any], stage: str) -> tuple[bool, dict[str, Any]]:
    quality = report.get("quality")
    if not isinstance(quality, dict):
        # Compatibility for older deterministic reports. Render is strict here;
        # completion/review should always emit quality in v1.2.
        if stage == "render":
            metrics = report.get("latex_metrics", {})
            complete = (
                isinstance(metrics, dict)
                and int(metrics.get("latex_errors", 1)) == 0
                and int(metrics.get("missing_characters", 1)) == 0
                and not report.get("missing_images", [])
            )
            quality = {"complete": complete}
        else:
            quality = {"complete": False, "reason": "missing quality contract"}
    return bool(quality.get("complete", False)), quality


def run_audit_stage(ctx: StageContext) -> None:
    logger: logging.Logger = ctx.logger
    lecture_path = ctx.workspace_root / "lecture" / "lecture.json"
    if not lecture_path.exists():
        raise StageError(f"缺少 lecture.json: {lecture_path}")
    lecture = read_json(lecture_path)
    if not isinstance(lecture, dict):
        raise StageError("lecture.json 根节点必须为 object。")
    if str(lecture.get("stage", "")) not in {"rendered", "audited"}:
        raise StageError("audit stage 要求 lecture.stage 为 rendered/audited。")

    stage_reports = {
        "completion": _read_report(ctx.workspace_root, "completion_report.json"),
        "review": _read_report(ctx.workspace_root, "review_report.json"),
        "render": _read_report(ctx.workspace_root, "render_report.json"),
    }
    checks: list[dict[str, Any]] = []
    all_ok = True
    for stage, report in stage_reports.items():
        ok, quality = _quality(report, stage)
        all_ok = all_ok and ok
        checks.append({"name": stage, "passed": ok, "quality": quality})

    has_notes = any(
        isinstance(item.get("quality"), dict) and bool(item["quality"].get("has_notes"))
        for item in checks
    )
    if all_ok:
        verdict = "PASS_WITH_NOTES" if has_notes else "PASS"
    else:
        verdict = "REVIEW_REQUIRED"
    report = {
        "schema_version": "1.2",
        "stage": "audit",
        "verdict": verdict,
        "summary": {
            "passed": sum(1 for x in checks if x["passed"]),
            "failed": sum(1 for x in checks if not x["passed"]),
            "has_notes": has_notes,
        },
        "checks": checks,
    }
    reports_dir = ctx.workspace_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "quality_report.json"
    md_path = reports_dir / "quality_report.md"
    atomic_write_json(json_path, report)
    md = ["# Video to Notes Quality Report", "", f"**Verdict: {verdict}**", ""]
    for item in checks:
        md.append(f"- {'PASS' if item['passed'] else 'FAIL'} — {item['name']}")
        if not item["passed"]:
            md.append(f"  - {item['quality']}")
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    lecture["audit"] = {"verdict": verdict, "report_json": str(json_path), "report_markdown": str(md_path)}
    lecture["stage"] = "audited"
    atomic_write_json(lecture_path, lecture)
    logger.info("[audit] verdict=%s", verdict)
