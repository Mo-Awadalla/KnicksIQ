"""Normalize NBA box scores and reconcile overtime periods for release exports."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

from app.models.game import Game

_PERIOD_SCORE = re.compile(r"^period(\d+)Score$")


_ISO_MINUTES = re.compile(r"^PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$")


_CLOCK_MINUTES = re.compile(r"^(\d+):(\d+(?:\.\d+)?)$")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


def _int(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    if value in (None, ""):
        return 0
    return int(float(value))


def _minutes(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = _ISO_MINUTES.match(text)
    if match:
        return int(match.group(1) or 0) + float(match.group(2) or 0) / 60
    match = _CLOCK_MINUTES.match(text)
    if match:
        return int(match.group(1)) + float(match.group(2)) / 60
    try:
        return float(text)
    except ValueError:
        return 0.0


def normalize_box_score(nba_game_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Map nba_api v3 names to the stable release schema."""
    team_stats: list[dict[str, Any]] = []
    for raw in payload.get("team_stats") or []:
        row = _json_safe(raw)
        team_stats.append(
            {
                "nba_game_id": nba_game_id,
                "team_id": row["teamTricode"],
                "points": _int(row, "points"),
                "field_goals_made": _int(row, "fieldGoalsMade"),
                "field_goals_attempted": _int(row, "fieldGoalsAttempted"),
                "three_pointers_made": _int(row, "threePointersMade"),
                "three_pointers_attempted": _int(row, "threePointersAttempted"),
                "free_throws_made": _int(row, "freeThrowsMade"),
                "free_throws_attempted": _int(row, "freeThrowsAttempted"),
                "offensive_rebounds": _int(row, "reboundsOffensive"),
                "defensive_rebounds": _int(row, "reboundsDefensive"),
                "rebounds": _int(row, "reboundsTotal"),
                "assists": _int(row, "assists"),
                "steals": _int(row, "steals"),
                "blocks": _int(row, "blocks"),
                "turnovers": _int(row, "turnovers"),
                "personal_fouls": _int(row, "foulsPersonal"),
                "plus_minus": _int(row, "plusMinusPoints"),
            }
        )

    player_stats: list[dict[str, Any]] = []
    player_definitions: list[dict[str, Any]] = []
    for raw in payload.get("player_stats") or []:
        row = _json_safe(raw)
        nba_player_id = _int(row, "personId")
        if not nba_player_id:
            continue
        position = str(row.get("position") or "").strip() or None
        team_id = str(row.get("teamTricode") or "").strip()
        full_name = " ".join(
            part
            for part in (str(row.get("firstName") or ""), str(row.get("familyName") or ""))
            if part
        ).strip()
        player_definitions.append(
            {
                "nba_player_id": nba_player_id,
                "full_name": full_name or str(row.get("nameI") or nba_player_id),
                "team_id": team_id,
                "position": position,
                "jersey_number": str(row.get("jerseyNum") or "").strip() or None,
            }
        )
        player_stats.append(
            {
                "nba_game_id": nba_game_id,
                "nba_player_id": nba_player_id,
                "team_id": team_id,
                "starter": position is not None,
                "position": position,
                "minutes": round(_minutes(row.get("minutes")), 4),
                "points": _int(row, "points"),
                "field_goals_made": _int(row, "fieldGoalsMade"),
                "field_goals_attempted": _int(row, "fieldGoalsAttempted"),
                "three_pointers_made": _int(row, "threePointersMade"),
                "three_pointers_attempted": _int(row, "threePointersAttempted"),
                "free_throws_made": _int(row, "freeThrowsMade"),
                "free_throws_attempted": _int(row, "freeThrowsAttempted"),
                "offensive_rebounds": _int(row, "reboundsOffensive"),
                "defensive_rebounds": _int(row, "reboundsDefensive"),
                "rebounds": _int(row, "reboundsTotal"),
                "assists": _int(row, "assists"),
                "steals": _int(row, "steals"),
                "blocks": _int(row, "blocks"),
                "turnovers": _int(row, "turnovers"),
                "personal_fouls": _int(row, "foulsPersonal"),
                "plus_minus": _int(row, "plusMinusPoints"),
            }
        )

    period_scores: list[dict[str, Any]] = []
    for raw in payload.get("line_scores") or []:
        row = _json_safe(raw)
        team_id = str(row.get("teamTricode") or "").strip()
        for key, value in row.items():
            match = _PERIOD_SCORE.match(key)
            if match and value is not None:
                period_scores.append(
                    {
                        "nba_game_id": nba_game_id,
                        "team_id": team_id,
                        "period": int(match.group(1)),
                        "points": int(value),
                    }
                )
    return {
        "team_game_stats": team_stats,
        "player_game_stats": player_stats,
        "period_scores": period_scores,
        "players": player_definitions,
    }


def complete_overtime_period_scores(
    game: Game,
    period_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fill summary-v3's missing overtime columns from cumulative PBP scores."""
    rows = [dict(row) for row in period_rows]
    expected = {
        game.home_team_id: game.home_score,
        game.away_team_id: game.away_score,
    }
    totals = {
        team_id: sum(row["points"] for row in rows if row["team_id"] == team_id)
        for team_id in expected
    }
    if totals == expected:
        return rows
    max_period = max((int(row["period"]) for row in event_rows), default=4)
    for period in range(5, max_period + 1):
        period_events = [row for row in event_rows if int(row["period"]) == period]
        if not period_events:
            continue
        cumulative = {
            game.home_team_id: max(int(row.get("home_score") or 0) for row in period_events),
            game.away_team_id: max(int(row.get("away_score") or 0) for row in period_events),
        }
        for team_id in expected:
            points = cumulative[team_id] - totals[team_id]
            if points < 0:
                raise ValueError(f"{game.nba_game_id}: invalid cumulative overtime score")
            rows.append(
                {
                    "nba_game_id": game.nba_game_id,
                    "team_id": team_id,
                    "period": period,
                    "points": points,
                }
            )
            totals[team_id] += points
    if totals != expected:
        raise ValueError(f"{game.nba_game_id}: overtime period scores do not reconcile")
    return rows
