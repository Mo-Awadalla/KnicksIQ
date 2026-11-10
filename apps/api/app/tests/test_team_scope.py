"""Team metric and scope regressions, independent of the canonical season totals."""

from datetime import date

from app.models.game import Game
from app.services.table_rag_games import _answer_from_games


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


def test_lowest_scoring_game():
    assert (
        "90 points"
        in _answer_from_games("What was the Knicks lowest-scoring game?", "2025-26", games()).answer
    )
