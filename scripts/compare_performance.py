from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(old: float, new: float) -> str:
    if old == 0:
        return "n/a"
    return f"{(new - old) / old * 100:+.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two video_to_notes performance reports.")
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    args = parser.parse_args()
    a = load(Path(args.baseline)).get("llm", {})
    b = load(Path(args.candidate)).get("llm", {})
    rows = [
        ("Input characters", "input_characters"),
        ("Images sent", "images_sent"),
        ("Requests executed", "requests_executed"),
        ("Requests reused", "requests_reused"),
    ]
    print(f"{'Metric':<24}{'Baseline':>12}{'Candidate':>12}{'Change':>12}")
    print("-" * 60)
    for label, key in rows:
        old = float(a.get(key, 0) or 0)
        new = float(b.get(key, 0) or 0)
        print(f"{label:<24}{int(old):>12}{int(new):>12}{pct(old, new):>12}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
