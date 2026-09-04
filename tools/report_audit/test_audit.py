"""Independent audit boundary tests with hand-calculated event score changes."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("audit", Path(__file__).with_name("audit.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
GAME = {"home_team_id": "NYK", "away_team_id": "BOS"}


def event(sequence, period, clock, home, away):
    return dict(sequence=sequence, period=period, clock=clock, home_score=home, away_score=away)


def test_cross_quarter_points_use_previous_observed_score():
    events = [
        event(1, 1, "01:00", 20, 20),
        event(2, 1, "00:19", 22, 20),
        event(3, 2, "12:00", 0, 0),
        event(4, 2, "11:00", 25, 20),
    ]
    result, error = audit.resolve_run(
        "NYK produced a 5-0 run in Q1 from 00:19 to 11:00.", GAME, events
    )
    assert error is None
    assert result["baseline_sequence"] == 1
    assert result["end_period"] == 2
    assert "Q1 00:19 to Q2 11:00" in audit.factual_run(result)


def test_wrong_totals_are_not_accepted_and_observations_remain_reviewable():
    result, error = audit.resolve_run(
        "NYK produced a 7-0 run in Q1 from 00:19 to 11:00.",
        GAME,
        [event(1, 1, "01:00", 20, 20), event(2, 1, "00:19", 22, 20), event(3, 2, "11:00", 25, 20)],
    )
    assert error == "run_points_or_boundary_mismatch"
    assert result["observed_intervals"][0]["points_for"] == 5


def test_multiple_free_throws_at_start_do_not_allow_cherry_picking():
    _, error = audit.resolve_run(
        "NYK produced a 3-0 run in Q1 from 01:00 to 00:30.",
        GAME,
        [
            event(1, 1, "02:00", 10, 10),
            event(2, 1, "01:00", 11, 10),
            event(3, 1, "01:00", 12, 10),
            event(4, 1, "00:30", 14, 10),
        ],
    )
    assert error == "run_points_or_boundary_mismatch"


def test_score_corrections_block_certification():
    _, error = audit.resolve_run(
        "NYK produced a 2-0 run in Q1 from 01:00 to 00:30.",
        GAME,
        [event(1, 1, "02:00", 10, 10), event(2, 1, "01:00", 9, 10)],
    )
    assert error == "nonmonotonic_canonical_score"


def test_review_flag_is_not_part_of_content_hash():
    assert audit.report_hash({"title": "x", "reviewed": True}) == audit.report_hash(
        {"title": "x", "reviewed": False}
    )
    assert audit.report_hash({"title": "x"}) != audit.report_hash({"title": "changed"})


def valid_payload():
    game = dict(GAME, nba_game_id="game", home_score=5, away_score=2, game_date="2026-01-01")
    report = {
        "nba_game_id": "game",
        "title": "NYK 5, BOS 2",
        "summary": "NYK defeated BOS 5-2 on 2026-01-01.",
        "player_notes": "[]",
        "turning_point": "BOS produced a 2-0 run in Q1 from 11:00 to 11:00.",
        "best_stretch": "NYK produced a 5-0 run in Q1 from 12:00 to 11:30.",
        "worst_stretch": "Knicks were outscored 2-0 from Q1 11:00 to Q1 11:00.",
        "reviewed": True,
    }
    events = [
        dict(e, nba_game_id="game")
        for e in [
            event(1, 1, "12:00", 2, 0),
            event(2, 1, "11:30", 5, 0),
            event(3, 1, "11:00", 5, 2),
        ]
    ]
    return {
        "manifest": {"version": "test", "expected_game_ids": ["game"], "expected_games": 1},
        "data": {
            "games": [game],
            "events": events,
            "player_game_stats": [],
            "players": [],
            "reports": [report],
        },
        "review_manifest": {"candidates": {"game": audit.report_hash(report)}},
    }


def test_full_audit_preserves_canonical_input_and_never_approves():
    payload = valid_payload()
    before = audit.digest(payload)
    result, proposal = audit.audit(payload)
    assert result["summary"]["passed"] == 1
    assert result["owner_approval"] is None
    assert result["release_approved"] is False
    assert proposal["reports"][0]["reviewed"] is False
    assert before == audit.digest(payload)


def test_tampered_content_is_excluded_from_proposal():
    payload = valid_payload()
    payload["data"]["reports"][0]["title"] = "NYK 50, BOS 2"
    result, proposal = audit.audit(payload)
    assert result["summary"]["unresolved"] == 1
    assert "content_hash_mismatch" in result["reports"][0]["issues"]
    assert "score_summary_mismatch" in result["reports"][0]["issues"]
    assert not proposal["reports"]


def test_manifest_coverage_mismatch_blocks_audit():
    payload = valid_payload()
    payload["manifest"]["expected_game_ids"].append("missing")
    result, _ = audit.audit(payload)
    assert result["coverage_complete"] is False
