"""Unit tests for `NbaApiDataSource`.

Tests use the `responses` library to intercept the `requests` calls
that nba_api makes under the hood. The fixtures are minimal but
realistic JSON responses in the exact shape nba_api expects.

These tests are pure unit tests — no DB, no RQ, no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import responses
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout
from worker_app.adapters.nba_api_source import NbaApiDataSource
from worker_app.core.config import NbaApiSettings

STATS_BASE = "https://stats.nba.com/stats"

LEAGUE_GAME_FINDER_HEADERS = [
    "SEASON_ID",
    "TEAM_ID",
    "TEAM_ABBREVIATION",
    "TEAM_NAME",
    "GAME_ID",
    "GAME_DATE",
    "MATCHUP",
    "WL",
    "MIN",
    "PTS",
    "FGM",
    "FGA",
    "FG_PCT",
    "FG3M",
    "FG3A",
    "FG3_PCT",
    "FTM",
    "FTA",
    "FT_PCT",
    "OREB",
    "DREB",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TOV",
    "PF",
    "PLUS_MINUS",
]

COMMON_TEAM_ROSTER_HEADERS = [
    "TeamID",
    "SEASON",
    "LeagueID",
    "PLAYER",
    "PLAYER_SLUG",
    "NUM",
    "POSITION",
    "HEIGHT",
    "WEIGHT",
    "BIRTH_DATE",
    "AGE",
    "EXP",
    "SCHOOL",
    "PLAYER_ID",
]


@pytest.fixture
def fast_settings() -> NbaApiSettings:
    """Settings that disable rate limiting and short backoff for fast tests."""
    return NbaApiSettings(
        seasons="2024-25",
        rate_remaining_per_minutes=0,  # no rate limiting in tests
        retry_attempts=3,
        retry_backoff_seconds=0.0,  # no sleep between retries
    )


@pytest.fixture
def data_source(fast_settings: NbaApiSettings, tmp_path: Path) -> NbaApiDataSource:
    """Write a minimal teams.json to tmp_path and return a configured source."""
    teams = [
        {"id": "NYK", "nba_team_id": 1610612752, "name": "Knicks", "abbreviation": "NYK"},
        {"id": "BOS", "nba_team_id": 1610612738, "name": "Celtics", "abbreviation": "BOS"},
        {"id": "PHI", "nba_team_id": 1610612755, "name": "76ers", "abbreviation": "PHI"},
        {"id": "MIA", "nba_team_id": 1610612748, "name": "Heat", "abbreviation": "MIA"},
        {"id": "LAL", "nba_team_id": 1610612747, "name": "Lakers", "abbreviation": "LAL"},
    ]
    (tmp_path / "teams.json").write_text(json.dumps(teams))
    return NbaApiDataSource(fast_settings, tmp_path)


def _league_game_finder_response(rows: list[list[Any]]) -> dict[str, Any]:
    return {
        "resultSets": [
            {
                "name": "LeagueGameFinderResults",
                "headers": LEAGUE_GAME_FINDER_HEADERS,
                "rowSet": rows,
            }
        ]
    }


def _playbyplay_v3_response(game_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "meta": {"version": 1, "request": "", "time": ""},
        "game": {
            "gameId": game_id,
            "actions": actions,
            "videoAvailable": 0,
        },
    }


def _common_team_roster_response(rows: list[list[Any]]) -> dict[str, Any]:
    return {
        "resultSets": [
            {
                "name": "CommonTeamRoster",
                "headers": COMMON_TEAM_ROSTER_HEADERS,
                "rowSet": rows,
            },
            {
                "name": "Coaches",
                "headers": [],
                "rowSet": [],
            },
        ]
    }


def test_constructor_requires_nyk_in_teams_json(
    fast_settings: NbaApiSettings, tmp_path: Path
) -> None:
    (tmp_path / "teams.json").write_text(json.dumps([{"id": "BOS", "nba_team_id": 1610612738}]))
    with pytest.raises(ValueError, match="NYK"):
        NbaApiDataSource(fast_settings, tmp_path)


def test_list_seasons_returns_configured_list(data_source: NbaApiDataSource) -> None:
    assert data_source.list_seasons() == ["2024-25"]


@responses.activate
def test_list_games_filters_to_knicks_and_dedupes(data_source: NbaApiDataSource) -> None:
    """`LeagueGameFinder` returns one row per team per game.

    Adapter should emit exactly one entry per GAME_ID, with the
    Knicks' opponent correctly identified via MATCHUP.
    """
    game_id = "0022400001"
    row_nyk_home = [
        "42024",  # SEASON_ID
        1610612752,  # TEAM_ID
        "NYK",  # TEAM_ABBREVIATION
        "Knicks",
        game_id,
        "OCT 22, 2024",
        "NYK vs. BOS",  # MATCHUP — home
        "W",
        240,
        132,
    ] + [0] * 18  # remaining columns
    row_bos_away = [
        "42024",
        1610612738,
        "BOS",
        "Celtics",
        game_id,
        "OCT 22, 2024",
        "BOS @ NYK",  # MATCHUP — away
        "L",
        240,
        109,
    ] + [0] * 18

    responses.add(
        responses.GET,
        f"{STATS_BASE}/leaguegamefinder",
        json=_league_game_finder_response([row_nyk_home, row_bos_away]),
        status=200,
    )

    games = data_source.list_games("2024-25")

    assert len(games) == 1
    g = games[0]
    assert g["nba_game_id"] == game_id
    assert g["season"] == "2024-25"
    assert g["home_team_id"] == "NYK"
    assert g["away_team_id"] == "BOS"
    assert g["home_score"] == 132
    assert g["away_score"] == 109
    assert g["status"] == "final"
    assert g["game_date"].isoformat() == "2024-10-22"


@responses.activate
def test_list_games_can_include_playoffs(data_source: NbaApiDataSource) -> None:
    regular_game_id = "0022400001"
    playoff_game_id = "0042400001"
    regular_rows = [
        [
            "22024",
            1610612752,
            "NYK",
            "Knicks",
            regular_game_id,
            "OCT 22, 2024",
            "NYK vs. BOS",
            "W",
            240,
            132,
        ]
        + [0] * 18,
        [
            "22024",
            1610612738,
            "BOS",
            "Celtics",
            regular_game_id,
            "OCT 22, 2024",
            "BOS @ NYK",
            "L",
            240,
            109,
        ]
        + [0] * 18,
    ]
    playoff_rows = [
        [
            "42024",
            1610612752,
            "NYK",
            "Knicks",
            playoff_game_id,
            "APR 20, 2025",
            "NYK vs. PHI",
            "W",
            240,
            101,
        ]
        + [0] * 18,
        [
            "42024",
            1610612755,
            "PHI",
            "76ers",
            playoff_game_id,
            "APR 20, 2025",
            "PHI @ NYK",
            "L",
            240,
            92,
        ]
        + [0] * 18,
    ]
    responses.add(
        responses.GET,
        f"{STATS_BASE}/leaguegamefinder",
        json=_league_game_finder_response(regular_rows),
        status=200,
    )
    responses.add(
        responses.GET,
        f"{STATS_BASE}/leaguegamefinder",
        json=_league_game_finder_response([]),
        status=200,
    )
    responses.add(
        responses.GET,
        f"{STATS_BASE}/leaguegamefinder",
        json=_league_game_finder_response(playoff_rows),
        status=200,
    )

    games = data_source.list_games("2024-25", include_playoffs=True)

    assert len(responses.calls) == 3
    assert {g["nba_game_id"] for g in games} == {regular_game_id, playoff_game_id}
    assert {g["nba_game_id"]: g["season_type"] for g in games} == {
        regular_game_id: "regular",
        playoff_game_id: "playoffs",
    }


@responses.activate
def test_list_team_roster_returns_historical_roster_rows(
    data_source: NbaApiDataSource,
) -> None:
    responses.add(
        responses.GET,
        f"{STATS_BASE}/commonteamroster",
        json=_common_team_roster_response(
            [
                [
                    1610612752,
                    "2025",
                    "00",
                    "Jalen Brunson",
                    "jalen-brunson",
                    "11",
                    "G",
                    "6-2",
                    "190",
                    "1996-08-31",
                    29,
                    "7",
                    "Villanova",
                    1628973,
                ]
            ]
        ),
        status=200,
    )

    roster = data_source.list_team_roster("NYK", "2025-26")

    assert len(roster) == 1
    assert roster[0]["PLAYER"] == "Jalen Brunson"
    assert roster[0]["PLAYER_ID"] == 1628973
    assert roster[0]["POSITION"] == "G"
    assert roster[0]["NUM"] == "11"


@responses.activate
def test_list_games_handles_empty_response(data_source: NbaApiDataSource) -> None:
    responses.add(
        responses.GET,
        f"{STATS_BASE}/leaguegamefinder",
        json=_league_game_finder_response([]),
        status=200,
    )
    assert data_source.list_games("2024-25") == []


@responses.activate
def test_get_game_parses_v3_response_into_seed_shape(data_source: NbaApiDataSource) -> None:
    """The v3 action -> seed event shape bridge."""
    game_id = "0022400001"
    actions = [
        {
            "actionNumber": 1,
            "clock": "PT12M00.00S",
            "period": 1,
            "teamId": 1610612752,
            "teamTricode": "NYK",
            "personId": 1628973,  # Brunson
            "playerName": "Jalen Brunson",
            "playerNameI": "J. Brunson",
            "xLegacy": None,
            "yLegacy": None,
            "shotDistance": 18,
            "shotResult": "Made",
            "isFieldGoal": 1,
            "scoreHome": 2,
            "scoreAway": 0,
            "pointsTotal": 2,
            "location": "H",
            "description": "Brunson 18ft two-point shot (2 PTS)",
            "actionType": "Made Shot",
            "subType": "Jump Shot",
            "videoAvailable": 0,
            "actionId": 1,
        },
        {
            "actionNumber": 2,
            "clock": "PT11M42.00S",
            "period": 1,
            "teamId": 0,
            "teamTricode": "",
            "personId": 0,
            "playerName": "",
            "playerNameI": "",
            "xLegacy": None,
            "yLegacy": None,
            "shotDistance": None,
            "shotResult": None,
            "isFieldGoal": 0,
            "scoreHome": 2,
            "scoreAway": 0,
            "pointsTotal": 0,
            "location": "",
            "description": "Start of 1st Quarter",
            "actionType": "Period Begin",
            "subType": "",
            "videoAvailable": 0,
            "actionId": 2,
        },
    ]
    responses.add(
        responses.GET,
        f"{STATS_BASE}/playbyplayv3",
        json=_playbyplay_v3_response(game_id, actions),
        status=200,
    )

    result = data_source.get_game(game_id)

    assert result is not None
    assert result["nba_game_id"] == game_id
    assert len(result["events"]) == 2

    made = result["events"][0]
    assert made["event_type"] == "made_shot"
    assert made["period"] == 1
    assert made["clock"] == "12:00"  # ISO duration converted
    assert made["team_id"] == "NYK"  # trigraph, not int
    assert made["player_id"] == 1628973  # nba_player_id int (job remaps to internal)
    assert made["player_name"] == "Jalen Brunson"
    assert made["home_score"] == 2
    assert made["away_score"] == 0
    assert made["shot_distance_ft"] == 18

    begin = result["events"][1]
    assert begin["event_type"] == "period_start"
    assert begin["team_id"] is None  # no team attribution for period events
    assert begin["player_id"] is None


@responses.activate
def test_get_game_skips_unknown_action_type(data_source: NbaApiDataSource) -> None:
    game_id = "0022400001"
    actions = [
        {
            "actionNumber": 1,
            "clock": "PT12M00.00S",
            "period": 1,
            "teamId": 0,
            "teamTricode": "",
            "personId": 0,
            "playerName": "",
            "playerNameI": "",
            "xLegacy": None,
            "yLegacy": None,
            "shotDistance": None,
            "shotResult": None,
            "isFieldGoal": 0,
            "scoreHome": 0,
            "scoreAway": 0,
            "pointsTotal": 0,
            "location": "",
            "description": "Mystery action",
            "actionType": "Unknown Action",
            "subType": "",
            "videoAvailable": 0,
            "actionId": 1,
        },
    ]
    responses.add(
        responses.GET,
        f"{STATS_BASE}/playbyplayv3",
        json=_playbyplay_v3_response(game_id, actions),
        status=200,
    )

    result = data_source.get_game(game_id)
    assert result is not None
    assert result["events"] == []


@responses.activate
def test_get_game_returns_none_on_http_error(
    data_source: NbaApiDataSource,
) -> None:
    """If the play-by-play fetch fails transiently past retries, return None.

    The job treats None as 'skip this game' rather than failing the
    whole ingest pipeline. (The adapter swallows the exception in
    `get_game` so a single bad game doesn't poison the season.)
    """
    responses.add(
        responses.GET,
        f"{STATS_BASE}/playbyplayv3",
        body=RequestsConnectionError("connection reset"),
    )

    result = data_source.get_game("0022400001")
    assert result is None


@responses.activate
def test_retry_succeeds_after_transient_503(data_source: NbaApiDataSource) -> None:
    """First call 503s, second succeeds — the adapter should return the data."""
    game_id = "0022400001"
    actions: list[dict[str, Any]] = []
    success_body = json.dumps(_playbyplay_v3_response(game_id, actions))

    responses.add(responses.GET, f"{STATS_BASE}/playbyplayv3", status=503)
    responses.add(responses.GET, f"{STATS_BASE}/playbyplayv3", body=success_body, status=200)

    result = data_source.get_game(game_id)
    assert result is not None
    assert result["nba_game_id"] == game_id
    assert len(responses.calls) == 2


@responses.activate
def test_retry_exhausts_after_three_503s(data_source: NbaApiDataSource) -> None:
    """Three 503s in a row → the adapter exhausts retries and returns None.

    `get_game` swallows the final exception so a single bad game
    doesn't poison the season ingest. The retry-count assertion
    confirms the retry budget was actually spent.
    """
    for _ in range(3):
        responses.add(responses.GET, f"{STATS_BASE}/playbyplayv3", status=503)

    assert data_source.get_game("0022400001") is None
    assert len(responses.calls) == 3


@responses.activate
def test_4xx_eventually_returns_none(data_source: NbaApiDataSource) -> None:
    """4xx surfaces as a non-JSON ValueError; the adapter retries and then
    `get_game` returns None.

    Note: a true 4xx-only no-retry path requires peeking at the
    response object (nba_api doesn't call `raise_for_status()`). The
    current behavior is "retry any non-HTTPError, then surface the
    final exception" — bounded by `retry_attempts` (3 here).
    """
    for _ in range(3):
        responses.add(responses.GET, f"{STATS_BASE}/playbyplayv3", status=400)

    assert data_source.get_game("0022400001") is None
    assert len(responses.calls) == 3


@responses.activate
def test_429_is_retried(data_source: NbaApiDataSource) -> None:
    """429 is rate-limiting — retry like a 5xx."""
    for _ in range(2):
        responses.add(responses.GET, f"{STATS_BASE}/playbyplayv3", status=429)
    responses.add(
        responses.GET,
        f"{STATS_BASE}/playbyplayv3",
        json=_playbyplay_v3_response("0022400001", []),
        status=200,
    )

    result = data_source.get_game("0022400001")
    assert result is not None
    assert len(responses.calls) == 3


@responses.activate
def test_timeout_is_retried(data_source: NbaApiDataSource) -> None:
    """Timeout is transient — retry."""
    for _ in range(2):
        responses.add(responses.GET, f"{STATS_BASE}/playbyplayv3", body=Timeout())
    responses.add(
        responses.GET,
        f"{STATS_BASE}/playbyplayv3",
        json=_playbyplay_v3_response("0022400001", []),
        status=200,
    )

    result = data_source.get_game("0022400001")
    assert result is not None
    assert len(responses.calls) == 3


def test_iso_duration_to_clock() -> None:
    """Direct test of the helper used in `_parse_pbp_v3_action`."""
    assert NbaApiDataSource._iso_duration_to_clock("PT12M00.00S") == "12:00"
    assert NbaApiDataSource._iso_duration_to_clock("PT05M30.00S") == "05:30"
    assert NbaApiDataSource._iso_duration_to_clock("PT00M00.50S") == "00:00"
    assert NbaApiDataSource._iso_duration_to_clock("PT11M42.00S") == "11:42"
    assert NbaApiDataSource._iso_duration_to_clock("") == "12:00"
    assert NbaApiDataSource._iso_duration_to_clock("bogus") == "bogus"


def test_parse_nba_game_date() -> None:
    from datetime import date

    assert NbaApiDataSource._parse_nba_game_date("OCT 22, 2024") == date(2024, 10, 22)
    assert NbaApiDataSource._parse_nba_game_date("APR 13, 2025") == date(2025, 4, 13)
