"""Team metric and scope regressions, independent of the canonical season totals."""

from datetime import date

import pytest
from app.models.game import Game
from app.services.table_rag import _answer_from_games
from app.services.team_scope import comparison_groups, scope_games


def games():
    return [
        Game(
            id=index,
            game_date=date(2026, month, day),
            home_team_id="NYK" if home else "BOS",
            away_team_id="BOS" if home else "NYK",
            home_score=own if home else other,
            away_score=other if home else own,
            season_type=phase,
            data_status="events_ready",
            source_name="test",
            source_url=None,
        )
        for index, (month, day, home, own, other, phase) in enumerate(
            [
                (1, 1, True, 120, 100, "regular"),
                (1, 20, False, 95, 105, "regular"),
                (2, 10, True, 110, 90, "regular"),
                (2, 20, False, 130, 110, "regular"),
                (3, 3, True, 90, 99, "regular"),
                (5, 2, False, 125, 100, "playoffs"),
            ],
            1,
        )
    ]


@pytest.mark.parametrize(
    ("question", "ids"),
    [
        ("How many home games did the Knicks win?", [1, 3, 5]),
        ("What was their record in the last 2 games?", [5, 6]),
        ("What was their record in the first 2 games?", [1, 2]),
        ("What was their record over the final 2 regular-season games?", [4, 5]),
        ("How did they perform from January 1 through January 15?", [1]),
        ("How many games did they play between March 1 and March 15?", [5]),
        ("What was their record after the All-Star break?", [4, 5, 6]),
    ],
)
def test_team_game_scopes(question, ids):
    assert [g.id for g in scope_games(question, games())] == ids


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What was the Knicks average margin?", "+11.0-point margin"),
        ("How many points per game did the Knicks allow?", "100.7 points per game"),
        ("What was the Knicks highest-scoring game?", "130 points"),
        ("What was the Knicks lowest-scoring game?", "90 points"),
        ("How many games did the Knicks score at least 120?", "In 3 of 6"),
        ("How many games did the Knicks hold opponents under 100?", "In 2 of 6"),
    ],
)
def test_team_question_preserves_requested_metric(question, expected):
    assert expected in _answer_from_games(question, "2025-26", games()).answer


def test_comparison_keeps_first_and_last_windows_separate():
    groups = comparison_groups("Compare their first 2 games with their last 2 games.", games())
    assert [[g.id for g in group] for _, group in groups] == [[1, 2], [5, 6]]
