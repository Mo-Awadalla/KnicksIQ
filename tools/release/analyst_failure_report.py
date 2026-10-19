"""Reduce live E2E response files to a per-stage failure report.

Reads the `.responses.jsonl` files written by analyst_live_e2e.py, one per run, and prints a
markdown report: staged counts per run, every distinct failure message with its stage and an
example, which providers served the requests, and how many choices each required slot offered.

    python tools/release/analyst_failure_report.py runs/A.responses.jsonl runs/B.responses.jsonl
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

CAPACITY = ("exceed", "cannot fit", "exceeds")
STRUCTURE = ("duplicate JSON key", "must be a JSON object", "JSON")


def stage_of(error: dict | None, calls: list[dict]) -> str:
    """Where the turn first went wrong, from the recorded exception and calls."""
    if any("provider_error" in call for call in calls):
        return "provider/request"
    if error is None:
        return "none"
    message, kind = error["message"], error["type"]
    if kind == "ValidationError":
        return "output structure"
    if any(word in message for word in CAPACITY):
        answered = any(kind_of(c) == "writer" and "raw" in c for c in calls)
        reviewed = any(kind_of(c) == "review" for c in calls)
        if answered and not reviewed:
            return "evidence preparation (capacity), after a valid writer answer"
        return "evidence preparation (capacity)"
    if any(word in message for word in STRUCTURE):
        return "output structure"
    if "claim" in message or "slot" in message or "related" in message:
        return "choice validation"
    if "Review" in message or "review" in message:
        return "independent review"
    return "other"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def kind_of(call: dict) -> str:
    """Writer or review call. Files without `kind` are classified by the `assertions` key."""
    if "kind" in call:
        return call["kind"]
    return "review" if '"assertions"' in call.get("raw", "") else "writer"


def staged(rows: list[dict]) -> dict[str, int]:
    """Counts of what each turn demonstrably did, from the recorded calls."""
    routed = [r for r in rows if r["model_calls"]]

    def calls(row: dict, kind: str) -> list[dict]:
        return [c for c in row["model_calls"] if kind_of(c) == kind]

    answered = [r for r in routed if any("raw" in c for c in calls(r, "writer"))]
    reviewed = [r for r in routed if calls(r, "review")]
    accepted = [r for r in routed if r["outcome"].startswith("validated")]
    return {
        "questions": len(rows),
        "reached the model": len(routed),
        "writer response received": len(answered),
        "reviewer reached": len(reviewed),
        "reviewer accepted": len(accepted),
        "met expectation": sum(r["meets_expectation"] for r in rows),
    }


def main(paths: list[str]) -> None:
    runs = {Path(p).name.removesuffix(".responses.jsonl"): load(Path(p)) for p in paths}
    print("## Staged counts\n")
    names = list(runs)
    print("| Stage | " + " | ".join(names) + " |")
    print("| --- | " + " | ".join("---:" for _ in names) + " |")
    counts = {name: staged(rows) for name, rows in runs.items()}
    for stage in next(iter(counts.values())):
        print(f"| {stage} | " + " | ".join(str(counts[n][stage]) for n in names) + " |")

    print("\n## First failure by stage and message\n")
    print("| Run | Stage | Message | Count | Example question |")
    print("| --- | --- | --- | ---: | --- |")
    for name, rows in runs.items():
        groups: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
        for row in rows:
            stage = stage_of(row["error"], row["model_calls"])
            if stage != "none":
                message = (row["error"] or {}).get("message", "") or next(
                    c["provider_error"] for c in row["model_calls"] if "provider_error" in c
                )
                groups[(stage, message)].append(row)
        for (stage, message), members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            print(f"| {name} | {stage} | {message[:90]} | {len(members)} | {members[0]['id']} |")

    print("\n## Review rejections\n")
    for name, rows in runs.items():
        rejected = [r for r in rows if r["outcome"] == "fallback:review_rejected"]
        print(f"- {name}: {len(rejected)} reviewer-rejected answers")

    print("\n## Providers that served requests\n")
    for name, rows in runs.items():
        served = collections.Counter(
            c.get("provider") for r in rows for c in r["model_calls"] if c.get("provider")
        )
        print(f"- {name}: {dict(served)}")

    print("\n## Choices offered per required slot\n")
    seen: collections.Counter[tuple[int, int]] = collections.Counter()
    for rows in runs.values():
        for row in rows:
            for call in row["model_calls"]:
                for slot in call.get("slots", []):
                    seen[(slot["claims"], slot["choices"])] += 1
    print("| Claims in slot | Choices in slot | Slots seen |")
    print("| ---: | ---: | ---: |")
    for (claims, choices), n in sorted(seen.items()):
        print(f"| {claims} | {choices} | {n} |")


if __name__ == "__main__":
    main(sys.argv[1:])
