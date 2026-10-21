"""Pure period arithmetic and scope policy for get_period_scoring.

No database access here: the handler loads period_scores and these functions decide what a
game contributes, how halves are derived, and which phases a question covers.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.query_resolution import ResolvedQuery

PHASE_ORDER = ("regular", "play_in", "playoffs")
_TEAM_NAMES = {
    "ATL": "Atlanta",
    "BOS": "Boston",
    "BKN": "Brooklyn",
    "CHA": "Charlotte",
    "CHI": "Chicago",
    "CLE": "Cleveland",
    "DAL": "Dallas",
    "DEN": "Denver",
    "DET": "Detroit",
    "GSW": "Golden State",
    "HOU": "Houston",
    "IND": "Indiana",
    "LAC": "LA Clippers",
    "LAL": "LA Lakers",
    "MEM": "Memphis",
    "MIA": "Miami",
    "MIL": "Milwaukee",
    "MIN": "Minnesota",
    "NOP": "New Orleans",
    "NYK": "New York",
    "OKC": "Oklahoma City",
    "ORL": "Orlando",
    "PHI": "Philadelphia",
    "PHX": "Phoenix",
    "POR": "Portland",
    "SAC": "Sacramento",
    "SAS": "San Antonio",
    "TOR": "Toronto",
    "UTA": "Utah",
    "WAS": "Washington",
}
PHASE_LABEL = {"regular": "regular season", "play_in": "play-in", "playoffs": "playoffs"}
REGULATION = (1, 2, 3, 4)


def label(period: int) -> str:
    if period <= 4:
        return f"Q{period}"
    return {5: "OT", 6: "2OT", 7: "3OT"}.get(period, f"{period - 4}OT")


def phase_label(phases: list[str]) -> str:
    unique = [phase for phase in PHASE_ORDER if phase in phases]
    if len(unique) == 1:
        return PHASE_LABEL[unique[0]]
    if set(unique) == {"regular", "playoffs"}:
        return "regular season and playoffs"
    return ", ".join(PHASE_LABEL[phase] for phase in unique) if unique else "selected games"


def team_name(team_id: str) -> str:
    return _TEAM_NAMES.get(team_id, team_id)


def opponent(game: Game) -> str:
    return game.away_team_id if game.home_team_id == "NYK" else game.home_team_id


def venue(game: Game) -> str:
    return "home" if game.home_team_id == "NYK" else "away"


def result(game: Game, tools: AnalystTools) -> str:
    return "W" if tools.score(game)[0] > tools.score(game)[1] else "L"


def period_view(
    tools: AnalystTools, game: Game, teams: dict[str, dict[int, int]]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return the complete period view for a game, or the gap that excludes it."""
    opponent_id = opponent(game)
    if game.status != "final":
        return None, {
            "game_id": game.id,
            "date": str(game.game_date),
            "opponent": opponent_id,
            "season_type": game.season_type,
            "reason": "game_not_final",
        }
    nyk = teams.get("NYK", {})
    opp = teams.get(opponent_id, {})
    missing = [label(period) for period in REGULATION if period not in nyk or period not in opp]
    if missing:
        return None, {
            "game_id": game.id,
            "date": str(game.game_date),
            "opponent": opponent_id,
            "season_type": game.season_type,
            "reason": "missing_regulation_periods",
            "missing": missing,
        }
    present = sorted(set(nyk) | set(opp))
    for period in present:
        if period in REGULATION:
            continue
        if period not in nyk or period not in opp:
            return None, {
                "game_id": game.id,
                "date": str(game.game_date),
                "opponent": opponent_id,
                "season_type": game.season_type,
                "reason": "incomplete_overtime",
                "missing": [f"{label(period)} for one team"],
            }
    nyk_final = sum(nyk[period] for period in present)
    opp_final = sum(opp[period] for period in present)
    if (nyk_final, opp_final) != tools.score(game):
        return None, {
            "game_id": game.id,
            "date": str(game.game_date),
            "opponent": opponent_id,
            "season_type": game.season_type,
            "reason": "period_rows_do_not_match_final_score",
            "period_points": [nyk_final, opp_final],
            "final": list(tools.score(game)),
        }
    first_half = [sum(nyk[p] for p in (1, 2)), sum(opp[p] for p in (1, 2))]
    second_half = [sum(nyk[p] for p in (3, 4)), sum(opp[p] for p in (3, 4))]
    return (
        {
            "periods": {str(period): [nyk[period], opp[period]] for period in present},
            "first_half": first_half,
            "second_half": second_half,
            "halftime_lead": first_half[0] - first_half[1],
            "final": [nyk_final, opp_final],
            "overtime": [label(period) for period in present if period > 4],
        },
        None,
    )


def extreme(entries: list[Any], key: Callable[[Any], Any], *, highest: bool) -> Any | None:
    """Deterministic pick: value, then earliest date, then lowest game id."""
    if not entries:
        return None
    if highest:
        return max(
            entries,
            key=lambda entry: (key(entry), -entry[0].game_date.toordinal(), -entry[0].id),
        )
    return min(
        entries,
        key=lambda entry: (key(entry), entry[0].game_date.toordinal(), entry[0].id),
    )


def game_ref(game: Game, period: int, pair: list[int], phase: str) -> dict[str, Any]:
    return {
        "game_id": game.id,
        "date": str(game.game_date),
        "opponent": opponent(game),
        "venue": venue(game),
        "season_type": game.season_type,
        "period": period,
        "label": label(period),
        "nyk_points": pair[0],
        "opponent_points": pair[1],
        "differential": pair[0] - pair[1],
        "phase": phase,
    }


def requested_periods(scope: ResolvedQuery, question: str, available: list[int]) -> list[int]:
    if scope.periods:
        return sorted({period for period in scope.periods if period in available})
    if re.search(r"\b(?:overtime|extra period|\bot\b)", question, re.I):
        return [period for period in available if period > 4]
    return available


def phase_groups(
    tools: AnalystTools, scope: ResolvedQuery, games: list[Game]
) -> list[tuple[str, str, list[str], list[Game]]]:
    """Apply the phase policy and return (metric suffix, label, phases, games).

    Season-level questions default to the regular season. Opponent questions break out every
    phase present. An explicitly named game or window is used as-is.
    """
    if scope.season_type:
        selected = [game for game in games if game.season_type == scope.season_type]
        if not selected:
            return []
        return [(scope.season_type, PHASE_LABEL[scope.season_type], [scope.season_type], selected)]
    specific = bool(
        (scope.game_ids and len(scope.game_ids) == 1)
        or scope.date_start
        or scope.date_end
        or scope.relative_game_count
    )
    overall = bool(re.search(r"\boverall\b", tools.question, re.I))
    if specific or scope.opponent_id or overall:
        phases = [
            phase for phase in PHASE_ORDER if any(game.season_type == phase for game in games)
        ]
        if overall or (specific and len(phases) > 1):
            return [("all_phases", phase_label(phases), phases, games)]
        return [
            (
                phase,
                PHASE_LABEL[phase],
                [phase],
                [game for game in games if game.season_type == phase],
            )
            for phase in phases
        ]
    regular = [game for game in games if game.season_type == "regular"]
    return [("regular", PHASE_LABEL["regular"], ["regular"], regular)] if regular else []
