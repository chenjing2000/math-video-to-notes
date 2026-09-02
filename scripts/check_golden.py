from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import yaml


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_contract(workspace: Path, contract: dict) -> list[str]:
    errors: list[str] = []
    lecture = load_json(workspace / "lecture" / "lecture.json")
    render = load_json(workspace / "reports" / "render_report.json")
    audit = load_json(workspace / "reports" / "quality_report.json")
    expect = contract.get("expect", {})

    problems = lecture.get("problems", [])
    figures = lecture.get("figures", [])
    derived = [x for x in lecture.get("supplements", []) if isinstance(x, dict) and x.get("type") == "derived_solution"]
    unverified = [x for x in derived if x.get("math_review_status") != "verified"]
    metrics = render.get("latex_metrics", {})

    checks = {
        "problems_min": len(problems) >= int(expect.get("problems_min", 0)),
        "figures_min": len(figures) >= int(expect.get("figures_min", 0)),
        "derived_solutions_min": len(derived) >= int(expect.get("derived_solutions_min", 0)),
        "unverified_derived_solutions": len(unverified) == int(expect.get("unverified_derived_solutions", 0)),
        "latex_errors": int(metrics.get("latex_errors", -1)) == int(expect.get("latex_errors", 0)),
        "missing_characters": int(metrics.get("missing_characters", -1)) == int(expect.get("missing_characters", 0)),
        "audit": str(audit.get("verdict")) == str(expect.get("audit", "PASS")),
    }
    for name, ok in checks.items():
        if not ok:
            errors.append(f"{name} failed")

    text = json.dumps(lecture, ensure_ascii=False)
    for needle in contract.get("contains", []):
        if str(needle) not in text:
            errors.append(f"missing content: {needle}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_root", type=Path)
    parser.add_argument("--contracts", type=Path, default=Path("golden"))
    args = parser.parse_args()
    failures = 0
    for path in sorted(args.contracts.glob("*.yaml")):
        contract = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ws = args.workspace_root / str(contract.get("workspace_name", path.stem))
        if not ws.exists():
            print(f"SKIP {path.name}: workspace missing: {ws}")
            continue
        errors = check_contract(ws, contract)
        if errors:
            failures += 1
            print(f"FAIL {path.name}: " + "; ".join(errors))
        else:
            print(f"PASS {path.name}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
