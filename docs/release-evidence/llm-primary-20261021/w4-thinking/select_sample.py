"""Pick the 30 questions measured in every arm of the reasoning experiment.

The sample is fixed so all three arms answer the same questions in the same order:

1. the first three ids (file order) of each of the seven scored categories;
2. then the first nine questions that failed a model stage in w4-bench trial 1, file order,
   skipping the ones step 1 already selected. That fills the sample to 30 without
   over-weighting a single category.

`follow_ups` is excluded, exactly as `analyst_live_e2e.sample` excludes it.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
QUESTIONS = ROOT / "apps/api/app/evaluation/questions.jsonl"
TRIAL1 = Path(__file__).resolve().parents[1] / "w4-bench" / "trial1.scored.jsonl"
PER_CATEGORY = 3
FAILED_FILL = 9


def main() -> None:
    cases = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]
    scored = [case for case in cases if case["category"] != "follow_ups"]
    seen: dict[str, int] = {}
    picked: list[dict[str, str]] = []
    for case in scored:
        count = seen.get(case["category"], 0)
        if count < PER_CATEGORY:
            seen[case["category"]] = count + 1
            picked.append({"id": case["id"], "category": case["category"], "why": "first-3"})
    chosen = {row["id"] for row in picked}
    outcomes = {
        row["id"]: row["outcome"]
        for row in (json.loads(line) for line in TRIAL1.read_text().splitlines() if line.strip())
    }
    for row in picked:
        if outcomes.get(row["id"], "").startswith("failed:"):
            row["why"] = "first-3+failed-trial1:" + outcomes[row["id"]]
    filled = 0
    for case in scored:
        if filled >= FAILED_FILL:
            break
        if case["id"] in chosen:
            continue
        outcome = outcomes.get(case["id"], "")
        if not outcome.startswith("failed:"):
            continue
        chosen.add(case["id"])
        picked.append({"id": case["id"], "category": case["category"], "why": outcome})
        filled += 1
    assert filled == FAILED_FILL, filled
    assert len(picked) == 21 + FAILED_FILL, len(picked)
    out = Path(__file__).with_name("sample.json")
    out.write_text(json.dumps(picked, indent=2) + "\n")
    print(json.dumps({"questions": len(picked), "path": str(out)}, indent=2))


if __name__ == "__main__":
    main()
