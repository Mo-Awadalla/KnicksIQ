"""Release recovery and v3 box-score normalization tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from app.models.game import Game
from worker_app.release_export import complete_overtime_period_scores, normalize_box_score


def test_normalize_box_score_maps_v3_fields_and_overtime() -> None:
    result = normalize_box_score(
        "0022500003",
        {
            "team_stats": [
                {
                    "teamTricode": "NYK",
                    "points": 101,
                    "fieldGoalsMade": 38,
                    "fieldGoalsAttempted": 82,
                    "threePointersMade": 12,
                    "threePointersAttempted": 31,
                    "freeThrowsMade": 13,
                    "freeThrowsAttempted": 16,
                    "reboundsOffensive": 9,
                    "reboundsDefensive": 31,
                    "reboundsTotal": 40,
                    "assists": 24,
                    "steals": 8,
                    "blocks": 5,
                    "turnovers": 11,
                    "foulsPersonal": 17,
                    "plusMinusPoints": 4,
                }
            ],
            "player_stats": [
                {
                    "teamTricode": "NYK",
                    "personId": 1628973,
                    "firstName": "Jalen",
                    "familyName": "Brunson",
                    "position": "G",
                    "jerseyNum": "11",
                    "minutes": "PT35M30.00S",
                    "points": 27,
                    "fieldGoalsMade": 10,
                    "fieldGoalsAttempted": 20,
                    "threePointersMade": 3,
                    "threePointersAttempted": 7,
                    "freeThrowsMade": 4,
                    "freeThrowsAttempted": 5,
                    "reboundsOffensive": 1,
                    "reboundsDefensive": 3,
                    "reboundsTotal": 4,
                    "assists": 8,
                    "steals": 1,
                    "blocks": 0,
                    "turnovers": 2,
                    "foulsPersonal": 2,
                    "plusMinusPoints": 6,
                }
            ],
            "line_scores": [
                {
                    "teamTricode": "NYK",
                    "period1Score": 22,
                    "period2Score": 24,
                    "period3Score": 20,
                    "period4Score": 25,
                    "period5Score": 10,
                    "score": 101,
                }
            ],
        },
    )

    team = result["team_game_stats"][0]
    player = result["player_game_stats"][0]
    assert team["team_id"] == "NYK"
    assert team["three_pointers_attempted"] == 31
    assert player["nba_player_id"] == 1628973
    assert player["starter"] is True
    assert player["minutes"] == 35.5
    assert sum(row["points"] for row in result["period_scores"]) == 101
    assert result["period_scores"][-1]["period"] == 5


def test_normalize_box_score_keeps_dnp_players_as_zero_rows() -> None:
    result = normalize_box_score(
        "0022500004",
        {
            "team_stats": [],
            "line_scores": [],
            "player_stats": [
                {
                    "teamTricode": "BOS",
                    "personId": 99,
                    "firstName": "Bench",
                    "familyName": "Player",
                    "position": None,
                    "minutes": None,
                    "points": None,
                }
            ],
        },
    )

    player = result["player_game_stats"][0]
    assert player["starter"] is False
    assert player["minutes"] == 0
    assert player["points"] == 0


def test_normalize_box_score_parses_clock_minutes_and_carries_seconds() -> None:
    result = normalize_box_score(
        "0022500005",
        {
            "team_stats": [],
            "line_scores": [],
            "player_stats": [
                {
                    "teamTricode": "NYK",
                    "personId": 11,
                    "firstName": "Test",
                    "familyName": "Starter",
                    "position": "G",
                    "minutes": "30:60",
                }
            ],
        },
    )

    assert result["player_game_stats"][0]["minutes"] == 31.0


def test_complete_overtime_period_scores_uses_cumulative_pbp() -> None:
    game = cast(
        Game,
        SimpleNamespace(
            nba_game_id="ot-game",
            home_team_id="NYK",
            away_team_id="DEN",
            home_score=113,
            away_score=110,
        ),
    )
    regulation = [
        {"nba_game_id": "ot-game", "team_id": "NYK", "period": period, "points": 25}
        for period in range(1, 5)
    ] + [
        {"nba_game_id": "ot-game", "team_id": "DEN", "period": period, "points": 25}
        for period in range(1, 5)
    ]
    events = [
        {"period": 5, "home_score": 102, "away_score": 100},
        {"period": 5, "home_score": 113, "away_score": 110},
    ]

    rows = complete_overtime_period_scores(game, regulation, events)

    overtime = [row for row in rows if row["period"] == 5]
    assert overtime == [
        {"nba_game_id": "ot-game", "team_id": "NYK", "period": 5, "points": 13},
        {"nba_game_id": "ot-game", "team_id": "DEN", "period": 5, "points": 10},
    ]
