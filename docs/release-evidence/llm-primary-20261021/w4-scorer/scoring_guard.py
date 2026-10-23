"""Guard the two honest-scoring false negatives without loosening the checks.

Reported by the live follow-up run (w4-followups), 10 of 38 failing turns:

1. ``analyst_checks._same_number`` lost the rounding tolerance when the right-hand raw
   text was empty, so 116.3 against a full-precision 116.28571428571429 claim failed.
2. ``followup_oracle.RECORD_PAIR`` forbade a trailing dot, so a sentence-final 69-32.
   was not recognised as the record.

A looser check would raise scores for the wrong reason. Each fix therefore ships with a
negative case:

* wrong rounding: 116.4, 116.28, 6.34 or a truncated 116.3 must not pass;
* a different number that happens to round the same at lower precision: 0.54 (the
  hundredth of an answer 54) must not match a claim 1.0, and a plain 2.8 must not match
  a claim 0.0 through its /100 form;
* a reversed record: 32-69 must not match 69-32;
* a date as a record: the 01-21 tail of 2026-01-21 must not match 1-21.

Run from the repository root:

    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/w4-scorer/scoring_guard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools" / "release"))

from analyst_checks import Corpus, Token, _backed, _same_number  # noqa: E402
from followup_oracle import (  # noqa: E402
    TurnExpectation,
    expectation_checks,
    matches_record,
)

CASES: list[tuple[str, bool, object]] = []


def check(label: str, expected: bool, value) -> None:
    CASES.append((label, expected, value))


# --- The reported false negatives: these must pass. -----------------------------------
check(
    "round 116.3 backs 116.28571428571429",
    True,
    _same_number(116.3, 116.28571428571429, "116.3", ""),
)
check(
    "round +2.8 backs 2.8333333333333335", True, _same_number(2.8, 2.8333333333333335, "+2.8", "")
)
check("round 6.33 backs 6.329268292682927", True, _same_number(6.33, 6.329268292682927, "6.33", ""))
check(
    "round 116.45 backs 116.45121951219512",
    True,
    _same_number(116.45, 116.45121951219512, "116.45", ""),
)
check(
    "round 116.5 backs 116.45121951219512",
    True,
    _same_number(116.5, 116.45121951219512, "116.5", ""),
)
check(
    "both written raws keep the min-precision rule",
    True,
    _same_number(116.3, 116.28571428571429, "116.3", "116.28571428571429"),
)

record = TurnExpectation(
    kind="record",
    filters={},
    question="What was the record?",
    games=101,
    fact="69-32",
    record=(69, 32),
)
check("sentence-final 69-32.", True, matches_record("New York went 69-32.", 69, 32, 101))
check("comma-terminated 69-32,", True, matches_record("New York went 69-32, done.", 69, 32, 101))
check("bare 69-32", True, matches_record("New York went 69-32", 69, 32, 101))
check(
    "expectation_checks sees sentence-final 69-32.",
    True,
    expectation_checks("New York went 69-32.", record, {}).get("record_ok"),
)

# --- Inflation guards: these must stay false. -----------------------------------------
check("wrong rounding 116.4", False, _same_number(116.4, 116.28571428571429, "116.4", ""))
check("wrong rounding 116.28 at 2dp", False, _same_number(116.28, 116.28571428571429, "116.28", ""))
check("wrong rounding 6.34", False, _same_number(6.34, 6.329268292682927, "6.34", ""))
check("truncation 116.3 against 116.381", False, _same_number(116.3, 116.381, "116.3", ""))
check(
    "integer answer gets no slack (116 vs 116.2857)",
    False,
    _same_number(116, 116.28571428571429, "116", ""),
)
check("integer answer gets no slack (54 vs 53.6)", False, _same_number(54, 53.6, "54", ""))
check("hundredth 0.54 does not match 1.0", False, _same_number(0.54, 1.0, "54", ""))
check(
    "answer 54 is not backed by an unrelated claim 1.0",
    False,
    _backed(Token("54", "number", value=54.0), Corpus(text="", numbers=[1.0], entities=set())),
)
check(
    "answer 2.8 is not backed by a claim 0.0 through /100",
    False,
    _backed(Token("2.8", "number", value=2.8), Corpus(text="", numbers=[0.0], entities=set())),
)
check(
    "plain answer 45 is not backed by a rate claim 0.45",
    False,
    _backed(Token("45", "number", value=45.0), Corpus(text="", numbers=[0.45], entities=set())),
)
check("reversed record 32-69.", False, matches_record("New York went 32-69.", 69, 32, 101))
check(
    "reversed record 32-69, done.", False, matches_record("New York went 32-69, done.", 69, 32, 101)
)
check(
    "reversed record via wins/losses wording",
    False,
    matches_record("32 wins and 69 losses", 69, 32, 101),
)
check("date 2026-01-21 is not record 1-21", False, matches_record("2026-01-21", 1, 21, 22))
check(
    "date in a sentence is not record 1-21",
    False,
    matches_record("Played on 2026-01-21 in New York.", 1, 21, 22),
)
check("season 2025-26 is not record 25-26", False, matches_record("2025-26", 25, 26, 51))
check("decimal tail 69-32.5 is not a record", False, matches_record("score 69-32.5", 69, 32, 101))
check("domain tail 69-32.txt is not a record", False, matches_record("69-32.txt", 69, 32, 101))
check("record must add up to the population", False, matches_record("69-32", 69, 32, 100))


def main() -> int:
    failures = 0
    for label, expected, value in CASES:
        ok = bool(value) is expected
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'} expected={expected!s:5} got={bool(value)!s:5} {label}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} checks agree with the intended rule")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
