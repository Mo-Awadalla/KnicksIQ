"""Repair acceptance tests with hand-calculated scoreboard intervals."""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location("repair", Path(__file__).with_name("repair.py"))
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def event(sequence, clock, home, away, period=1):
    return dict(sequence=sequence, period=period, clock=clock, home_score=home, away_score=away)


def test_selection_includes_same_clock_free_throws_and_all_end_events():
    game = {"nba_game_id": "x", "home_team_id": "NYK", "away_team_id": "BOS"}
    intervals, exceptions = repair.select_intervals(
        game,
        [
            event(1, "12:00", 0, 2),
            event(2, "10:00", 2, 2),
            event(3, "10:00", 3, 2),
            event(4, "09:00", 5, 2),
            event(5, "09:00", 0, 0),
            event(6, "06:00", 5, 4),
        ],
    )
    assert not exceptions
    best = intervals["best_stretch"]
    assert (best["points_for"], best["points_against"]) == (5, 0)
    assert (best["start_sequence"], best["end_sequence"]) == (2, 5)
    assert intervals["worst_stretch"]["team_id"] == "BOS"


def test_selection_cannot_cross_score_correction_or_period():
    game = {"nba_game_id": "x", "home_team_id": "NYK", "away_team_id": "BOS"}
    intervals, exceptions = repair.select_intervals(
        game,
        [
            event(1, "03:00", 2, 2),
            event(2, "02:00", 5, 2),
            event(3, "01:30", 4, 2),
            event(4, "01:00", 7, 2),
            event(5, "12:00", 9, 2, period=2),
            event(6, "11:00", 9, 4, period=2),
        ],
    )
    assert exceptions[0]["sequence"] == 3
    for interval in intervals.values():
        assert not interval["start_sequence"] <= 3 <= interval["end_sequence"]
        assert interval["start_period"] == interval["end_period"]


def test_full_repair_preserves_canonical_data_and_requires_owner_review():
    from test_audit import valid_payload

    payload = valid_payload()
    before = repair.digest(payload)
    candidate, proposal, result = repair.repair(payload)
    assert repair.digest(payload) == before
    assert result["summary"]["passed"] == 1
    assert not result["release_approved"]
    assert result["owner_approval"] is None
    assert proposal["approvals"] == candidate["review_manifest"]["approvals"] == {}
    assert all(not r["reviewed"] for r in candidate["data"]["reports"])
    assert len(result["replaced_claims"]) == 3
    for key in payload["data"]:
        if key != "reports":
            assert payload["data"][key] == candidate["data"][key]
