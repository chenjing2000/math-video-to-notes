from __future__ import annotations

from typing import Any


def summarize_checks(checks: list[dict[str, Any]]) -> dict[str, int]:
    issues = [issue for check in checks for issue in check.get("issues", [])]
    return {
        "issues": len(issues),
        "errors": sum(1 for x in issues if x.get("severity") == "error"),
        "warnings": sum(1 for x in issues if x.get("severity") == "warning"),
        "info": sum(1 for x in issues if x.get("severity") == "info"),
    }


def decide_verdict(
    checks: list[dict[str, Any]],
    *,
    fail_on_warning: bool = False,
) -> str:
    summary = summarize_checks(checks)
    blocked = summary["errors"] > 0
    if fail_on_warning:
        blocked = blocked or summary["warnings"] > 0
    return "REVIEW_REQUIRED" if blocked else "PASS"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# video_to_notes Quality Report",
        "",
        f"**Verdict:** `{report['verdict']}`",
        "",
        "## Summary",
        "",
        f"- Errors: {report['summary']['errors']}",
        f"- Warnings: {report['summary']['warnings']}",
        f"- Info: {report['summary']['info']}",
        "",
    ]

    for check in report.get("checks", []):
        lines.append(f"## {check['name'].title()} Audit")
        lines.append("")
        metrics = check.get("metrics", {})
        for key, value in metrics.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

        issues = check.get("issues", [])
        if not issues:
            lines.append("No blocking issues.")
            lines.append("")
            continue

        lines.append("### Issues")
        lines.append("")
        for issue in issues:
            target = f" (`{issue['target_id']}`)" if issue.get("target_id") else ""
            lines.append(
                f"- **{issue['severity'].upper()}** `{issue['code']}`{target}: "
                f"{issue['message']}"
            )
        lines.append("")

    if report["verdict"] == "PASS":
        lines.extend([
            "## Result",
            "",
            "All blocking quality gates passed.",
            "",
        ])
    else:
        lines.extend([
            "## Result",
            "",
            "Manual review is required before this lecture is treated as final.",
            "",
        ])

    return "\n".join(lines)
