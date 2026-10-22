"""The reversed-record gate must fire on W-L records only, never on other number pairs.

Claims: wins 4, losses 1 over the same five games. Every sentence uses only backed numbers.
No database, no model.

    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/opencode-go/record_order_controls.py
"""

from app.services.analyst_review_checks import record_order_issues
from app.services.evidence_contracts import VerifiedClaim, split_review_spans

GAMES = [1, 2, 3, 4, 5]


def claim(metric: str, value: int) -> VerifiedClaim:
    return VerifiedClaim.create(
        subject_id="team:NYK",
        metric_id=metric,
        metric_definition_version="box-score-v1",
        value=value,
        unit="games",
        population="archived Knicks games",
        filters={},
        season="2025-26",
        season_type=None,
        game_ids=GAMES,
        window=None,
        sample_size=5,
        denominator=None,
        baseline_claim_ids=[],
        calculation_version="analyst-v1",
        release_id="r",
        supporting_evidence_ids=[],
        coverage_limitations=[],
        eligibility={},
        statement=f"{metric} {value}",
    )


CLAIMS = {c.claim_id: c for c in (claim("wins", 4), claim("losses", 1))}

# (sentence, must be flagged)
CASES = [
    ("Over their last 5 games, the Knicks went 1-4.", True),
    ("The Knicks had a 1-4 record over their last 5 games.", True),
    ("They finished 1-4 in that stretch.", True),
    ("Over their last 5 games, the Knicks went 4-1.", False),
    ("Brunson shot 1-4 from three in the opener.", False),
    ("Towns went 1-4 from the line.", False),
    ("The Knicks trailed 1-4 early in the first quarter.", False),
    ("They opened on a 4-1 run and later gave up a 1-4 stretch.", False),
    ("Hart was 1-4 shooting in the fourth quarter.", False),
]


def main() -> None:
    bad = 0
    for sentence, want in CASES:
        flagged = bool(record_order_issues(split_review_spans(sentence), CLAIMS))
        ok = flagged == want
        bad += not ok
        print("OK " if ok else "BAD", f"flagged={flagged} want={want}: {sentence}")
    print("FAILURES", bad)


main()
