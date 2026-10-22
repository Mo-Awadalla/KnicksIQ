#!/usr/bin/env python3
"""Per-category honest score per trial, with spread, from ab_runner rows.

The pending base/head live measurement writes <label>.rows.jsonl. This turns one or two
of those files into the acceptance table without re-scoring anything.

  python3 .../summarize_trials.py final/budget-16000.rows.jsonl
  python3 .../summarize_trials.py w3declines-base.rows.jsonl w3declines-head.rows.jsonl
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def table(name: str, rows: list[dict]) -> list[str]:
    trials = sorted({row["trial"] for row in rows})
    by: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        by[row["category"]][row["trial"]].append(row)
    lines = [f"### {name}", "", "| Category | " + " | ".join(f"T{t + 1}" for t in trials)
             + " | Spread | Failures |", "| --- | " + " | ".join("---:" for _ in trials)
             + " | ---: | --- |"]
    for category in sorted(by):
        scores = [
            sum(int(row["score"]["meets_expectation"]) for row in by[category][t])
            for t in trials
        ]
        counts = [len(by[category][t]) for t in trials]
        failures = Counter(
            failure.split(":")[0]
            for t in trials
            for row in by[category][t]
            for failure in row["score"]["failures"]
        )
        lines.append(
            f"| {category} | " + " | ".join(f"{s}/{c}" for s, c in zip(scores, counts, strict=True))
            + f" | {max(scores) - min(scores)} | "
            + ", ".join(f"{k} {v}" for k, v in failures.most_common(3)) + " |"
        )
    totals = [
        sum(int(row["score"]["meets_expectation"]) for row in rows if row["trial"] == t)
        for t in trials
    ]
    counts = [sum(1 for row in rows if row["trial"] == t) for t in trials]
    lines.append(
        f"| **Total** | " + " | ".join(f"**{s}/{c}**" for s, c in zip(totals, counts, strict=True))
        + f" | **{max(totals) - min(totals)}** | |"
    )
    answered_unsupported = [
        row for row in rows if row["category"] == "unsupported" and not row["score"]["checks"]["declined"]
    ]
    lines += [
        "",
        f"Unsupported answered instead of declined: {len(answered_unsupported)}"
        f" / {sum(1 for row in rows if row['category'] == 'unsupported')}",
    ]
    for row in answered_unsupported:
        lines.append(
            f"- trial {row['trial'] + 1} {row['id']}: {row['outcome']} | "
            + " ".join(row["score"]["failures"])
        )
    return lines


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    lines: list[str] = []
    for name in sys.argv[1:]:
        path = Path(name)
        rows = load(path)
        lines += table(path.name, rows) + [""]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
