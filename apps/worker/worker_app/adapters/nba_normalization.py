"""NBA endpoint dates, clocks, season types and play-by-play event normalization."""

from __future__ import annotations

import re
from collections.abc import Collection
from datetime import date
from typing import Any

_ACTION_TYPE_MAP: dict[str, str] = {
    "Made Shot": "made_shot",
    "Missed Shot": "missed_shot",
    "Rebound": "rebound",
    "Turnover": "turnover",
    "Foul": "foul",
    "Free Throw": "free_throw",
    "Substitution": "substitution",
    "Timeout": "timeout",
    "Jump Ball": "jump_ball",
    "Period Begin": "period_start",
    "Period End": "period_end",
    "Violation": "violation",
    "Ejection": "ejection",
}


_ISO_DURATION_RE = re.compile(r"^PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$")


def parse_nba_game_date(value: str) -> date:
    """Parse NBA's `GAME_DATE` strings.

    `LeagueGameFinder` has returned both ISO dates (`2026-04-12`)
    and legacy display dates (`OCT 22, 2024`) depending on endpoint
    version / nba_api release.
    """
    from datetime import datetime

    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.strptime(value, "%b %d, %Y").date()


def normalize_season_type(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    if normalized == "playin":
        return "play_in"
    if normalized == "playoffs":
        return "playoffs"
    return "regular"


def iso_duration_to_clock(value: str) -> str:
    """Convert ISO 8601 duration ('PT12M00.00S') to 'MM:SS'."""
    if not value:
        return "12:00"
    match = _ISO_DURATION_RE.match(value)
    if not match:
        return value  # pass through; parser tolerates non-standard clocks
    minutes = int(match.group(1) or 0)
    seconds = float(match.group(2) or 0)
    return f"{minutes:02d}:{int(seconds):02d}"


def parse_pbp_v3_action(action: Any, known_teams: Collection[str]) -> dict[str, Any] | None:
    """Translate one nba_api v3 action row into a seed-shaped event dict.

    The dict shape matches the `events` array in `seed/games.json`:
    `period`, `clock`, `event_type`, `description`, `team_id` (trigraph),
    `player_id` (nba_player_id int, remapped by the job), `home_score`,
    `away_score`, optional `shot_distance_ft`.
    """
    if not isinstance(action, dict):
        return None

    action_type = str(action.get("actionType") or "").strip()
    event_type = _ACTION_TYPE_MAP.get(action_type)
    if event_type is None:
        return None  # unknown action type — skip rather than fabricate

    team_tricode = action.get("teamTricode")
    team_id = str(team_tricode).strip().upper() or None
    if team_id and team_id not in known_teams:
        team_id = None  # unknown team trigraph (e.g. from ASG); drop attribution

    person_id = action.get("personId")
    player_id = int(person_id) if person_id else None

    try:
        home_score = int(action.get("scoreHome") or 0)
    except (TypeError, ValueError):
        home_score = 0
    try:
        away_score = int(action.get("scoreAway") or 0)
    except (TypeError, ValueError):
        away_score = 0

    event: dict[str, Any] = {
        "period": int(action.get("period") or 1),
        "clock": iso_duration_to_clock(str(action.get("clock") or "")),
        "event_type": event_type,
        "description": str(action.get("description") or ""),
        "team_id": team_id,
        "player_id": player_id,
        "player_name": str(action.get("playerName") or "").strip() or None,
        "home_score": home_score,
        "away_score": away_score,
    }

    # Optional: shot_distance_ft (only meaningful for shot events).
    shot_distance = action.get("shotDistance")
    if event_type in ("made_shot", "missed_shot", "free_throw") and shot_distance:
        try:
            event["shot_distance_ft"] = int(shot_distance)
        except (TypeError, ValueError):
            pass

    return event
