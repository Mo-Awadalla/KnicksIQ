from types import SimpleNamespace as Row

from app.services.verified_runs import verified_runs


def event(sequence, home, away, *, period=1, clock="1:00"):
    return Row(sequence=sequence, home_score=home, away_score=away, period=period, clock=clock)


GAME = Row(id=1, home_team_id="NYK", away_team_id="BOS")


def test_run_uses_inclusive_cumulative_scores_and_retains_explicit_periods():
    rows = [
        event(1, 10, 8),
        event(2, 13, 8),
        event(3, 0, 0),
        event(4, 15, 10, period=2, clock="11:50"),
    ]
    run = Row(
        id=7, team_id="NYK", start_sequence=2, end_sequence=4, points_for=99, points_against=0
    )
    result = verified_runs(GAME, rows, [run])[0]
    assert (result["points_for"], result["points_against"], result["score_delta"]) == (5, 2, 3)
    assert (result["period"], result["end_period"]) == (1, 2)
    assert (result["start_sequence"], result["end_sequence"], result["event_count"]) == (2, 4, 3)
    assert "Q2 11:50" in result["summary"]
    assert run.points_for == 99
    assert rows[2].home_score == 0


def test_run_crossing_score_correction_is_not_certified_but_later_window_is():
    rows = [event(1, 10, 8), event(2, 13, 8), event(3, 12, 8), event(4, 15, 8), event(5, 18, 8)]
    unsafe = Row(team_id="NYK", start_sequence=2, end_sequence=4)
    later = Row(team_id="NYK", start_sequence=4, end_sequence=5)
    result = verified_runs(GAME, rows, [unsafe, later])
    assert len(result) == 1
    assert result[0]["start_sequence"] == 4
    assert result[0]["points_for"] == 6


def test_away_run_and_unknown_boundary():
    rows = [event(1, 10, 8), event(2, 10, 11), event(3, 12, 14)]
    valid = Row(team_id="BOS", start_sequence=2, end_sequence=3)
    missing = Row(team_id="BOS", start_sequence=2, end_sequence=99)
    result = verified_runs(GAME, rows, [valid, missing])
    assert len(result) == 1
    assert (result[0]["points_for"], result[0]["points_against"]) == (6, 2)
