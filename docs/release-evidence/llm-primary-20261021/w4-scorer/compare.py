"""Compare the pre-fix and post-fix offline rescores in this directory.

The two artifacts were produced by the same commands, one on the base commit and one after
the scoring fix. This script prints the per-category honest counts and every verdict that
changed, with the claim value that justifies a newly accepted rounded number or record.

    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/w4-scorer/compare.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "tools" / "release"))

from analyst_checks import _extract, claim_corpus  # noqa: E402
from analyst_scoring import _same_number  # noqa: E402
from followup_bench import _reconstruct_citations  # noqa: E402
from followup_oracle import matches_record  # noqa: E402

SETS = [
    ("scoring/heldout-60", "heldout-60"),
    ("final/budget-16000.trial1", "budget-16000-trial1"),
    ("final/budget-16000.trial2", "budget-16000-trial2"),
    ("w4-bench/trial1", "w4-bench-trial1"),
    ("w4-bench/trial2", "w4-bench-trial2"),
]
RESPONSES = {
    "heldout-60": "scoring/heldout-60.responses.jsonl",
    "budget-16000-trial1": "final/budget-16000.trial1.responses.jsonl",
    "budget-16000-trial2": "final/budget-16000.trial2.responses.jsonl",
    "w4-bench-trial1": "w4-bench/trial1.responses.jsonl",
    "w4-bench-trial2": "w4-bench/trial2.responses.jsonl",
}
EVIDENCE = HERE.parent


def places(raw: str) -> int:
    return len(raw.split(".", 1)[1]) if "." in raw else 0


def old_same_number(left: float, right: float, left_raw: str = "", right_raw: str = "") -> bool:
    """The scorer as it was on the base commit, for classifying a changed row only."""
    import math

    if math.isclose(left, right, rel_tol=0, abs_tol=1e-9):
        return True
    left_places = places(left_raw)
    right_places = places(right_raw)
    p = min(left_places, right_places) if left_places or right_places else 0
    tolerance = 0.5 * 10 ** (-p) if p else 0.0
    return abs(left - right) <= tolerance + 1e-9


def candidates(token) -> list[float]:
    values = [token.value] if token.value is not None else []
    if token.kind == "pair":
        values = list(token.values)
    if token.kind == "percent" and token.value is not None:
        values.append(token.value / 100)
    return values


def rounding_reason(answer: str, citations: list[dict], raw: str) -> str | None:
    corpus = claim_corpus(citations)
    for token in _extract(answer):
        if token.raw != raw:
            continue
        for candidate in candidates(token):
            for item in corpus.numbers:
                if not old_same_number(candidate, item, token.raw.rstrip("%"), "") and _same_number(
                    candidate, item, token.raw.rstrip("%"), ""
                ):
                    return f"{raw} is {item!r} rounded to {places(token.raw.rstrip('%'))}dp"
    return None


def load_rows(name: str) -> dict[str, dict]:
    return {
        row["id"]: row
        for row in (
            json.loads(line)
            for line in (HERE / f"before/{name}.scored.jsonl").read_text().splitlines()
        )
    }, {
        row["id"]: row
        for row in (
            json.loads(line)
            for line in (HERE / f"after/{name}.scored.jsonl").read_text().splitlines()
        )
    }


def response_changes() -> list[dict]:
    changes = []
    for source, name in SETS:
        before, after = load_rows(name)
        responses = {
            row["id"]: row
            for row in (
                json.loads(line) for line in (EVIDENCE / RESPONSES[name]).read_text().splitlines()
            )
        }
        for rid, old in before.items():
            new = after[rid]
            if old["meets_expectation"] == new["meets_expectation"]:
                continue
            raw = responses[rid]
            reason = None
            if new["meets_expectation"]:
                reasons = [
                    rounding_reason(raw.get("answer", ""), raw.get("citations") or [], token)
                    for token in old["checks"]["unbacked_numbers"]
                ]
                reasons = [item for item in reasons if item]
                reason = "; ".join(reasons) or "missing reason"
            changes.append(
                {
                    "source": source,
                    "id": rid,
                    "category": old["category"],
                    "old": old["meets_expectation"],
                    "new": new["meets_expectation"],
                    "old_failures": old["failures"],
                    "new_failures": new["failures"],
                    "old_unbacked": old["checks"]["unbacked_numbers"],
                    "new_unbacked": new["checks"]["unbacked_numbers"],
                    "reason": reason,
                    "answer": raw.get("answer", ""),
                }
            )
    return changes


def followup_changes() -> tuple[list[dict], dict, dict]:
    before = json.loads((HERE / "before/followups.json").read_text())
    after = json.loads((HERE / "after/followups.json").read_text())
    changes = []
    for sid, runs in before["sessions"].items():
        for index, run in enumerate(runs):
            new_run = after["sessions"][sid][index]
            for turn_index, turn in enumerate(run["turns"]):
                new_turn = new_run["turns"][turn_index]
                if turn["cause"] == new_turn["cause"]:
                    continue
                answer = turn.get("answer", "")
                reason = None
                if new_turn["cause"] == "ok":
                    if not turn["expected_ok"] and new_turn["expected_ok"]:
                        wins, losses = turn["expected"]["record"] or (0, 0)
                        games = turn["expected"]["scope"]["game_count"]
                        reason = (
                            f"record {wins}-{losses} over {games} accepted sentence-final"
                            if (matches_record(answer, wins, losses, games))
                            else "record reason missing"
                        )
                    else:
                        citations = _reconstruct_citations({**turn, "checks": {}}, None)
                        reasons = [
                            rounding_reason(answer, citations, token)
                            for token in turn["checks"]["unbacked_numbers"]
                        ]
                        reasons = [item for item in reasons if item]
                        reason = "; ".join(reasons) or "missing reason"
                changes.append(
                    {
                        "source": "w4-followups",
                        "session": sid,
                        "trial": run.get("trial"),
                        "turn": turn["turn"],
                        "category": run.get("category"),
                        "old": turn["cause"],
                        "new": new_turn["cause"],
                        "old_honest": turn["honest_ok"],
                        "new_honest": new_turn["honest_ok"],
                        "old_expected": turn["expected_ok"],
                        "new_expected": new_turn["expected_ok"],
                        "old_unbacked": turn["checks"]["unbacked_numbers"],
                        "new_unbacked": new_turn["checks"]["unbacked_numbers"],
                        "reason": reason,
                        "answer": answer,
                    }
                )
    return changes, before["totals"], after["totals"]


def category_table(name: str) -> dict[str, dict]:
    before, after = load_rows(name)
    table: dict[str, dict] = {}
    for rid, old in before.items():
        row = table.setdefault(old["category"], {"questions": 0, "old": 0, "new": 0})
        row["questions"] += 1
        row["old"] += int(old["meets_expectation"])
        row["new"] += int(after[rid]["meets_expectation"])
    return table


def main() -> int:
    print("## Response artifacts: honest passes per category (before -> after)")
    tables = {}
    for _, name in SETS:
        table = category_table(name)
        tables[name] = table
        print(f"\n### {name}")
        print("| Category | Questions | Before | After |")
        print("| --- | ---: | ---: | ---: |")
        for category, row in table.items():
            print(f"| {category} | {row['questions']} | {row['old']} | {row['new']} |")
        total = {
            key: sum(row[key] for row in table.values()) for key in ("questions", "old", "new")
        }
        print(f"| **Total** | **{total['questions']}** | **{total['old']}** | **{total['new']}** |")
    changes = response_changes()
    followups, before_totals, after_totals = followup_changes()
    print("\n## Follow-up artifact")
    print(
        f"turns {before_totals['turn_passes']}/{before_totals['turns']} -> "
        f"{after_totals['turn_passes']}/{after_totals['turns']}; sessions "
        f"{before_totals['session_passes']}/{before_totals['session_runs']} -> "
        f"{after_totals['session_passes']}/{after_totals['session_runs']}"
    )
    print("\n## Changed rows")
    for change in changes + followups:
        label = change.get("session") or change["id"]
        trial = f" trial {change['trial']}" if change.get("trial") is not None else ""
        turn = f" turn {change['turn']}" if change.get("turn") is not None else ""
        print(
            f"- {change['source']} {label}{trial}{turn} [{change.get('category')}]: "
            f"{change['old']} -> {change['new']}: {change['reason']}"
        )
    failures = [change for change in changes + followups if change["new"] is False]
    print(f"\npass->fail changes: {len(failures)}")
    for change in failures:
        print(" ", change)
    out = {
        "tables": tables,
        "followups": {"before": before_totals, "after": after_totals},
        "changes": changes + followups,
        "pass_to_fail": failures,
    }
    (HERE / "comparison.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nwrote {HERE / 'comparison.json'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
