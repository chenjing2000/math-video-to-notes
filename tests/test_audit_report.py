from video_to_notes.audit.report import (
    decide_verdict,
    render_markdown,
    summarize_checks,
)


def test_verdict_pass_without_errors():
    checks = [{
        "name": "x",
        "metrics": {},
        "issues": [{
            "severity": "warning",
            "code": "w",
            "message": "warning",
        }],
    }]
    assert decide_verdict(checks) == "PASS"
    assert summarize_checks(checks)["warnings"] == 1


def test_verdict_review_required_with_error():
    checks = [{
        "name": "x",
        "metrics": {},
        "issues": [{
            "severity": "error",
            "code": "e",
            "message": "error",
        }],
    }]
    report = {
        "verdict": decide_verdict(checks),
        "summary": summarize_checks(checks),
        "checks": checks,
    }
    assert report["verdict"] == "REVIEW_REQUIRED"
    assert "REVIEW_REQUIRED" in render_markdown(report)
