"""Held-out v2 questions: exact statistics, date windows, comparisons and unsupported asks.

Every fact builder reads the active release passed in by build.py. The season-phase policy is
imported from app.evaluation.heldout_phase so both held-out sets resolve phases identically.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.evaluation.heldout_phase import Phase, season_type_for

from .facts import (
    Archive,
    avg_margin,
    avg_opponent_points,
    avg_points,
    point_differential,
    record,
)

FactBuilder = Callable[[Archive, Phase], tuple[list[str], list[str], list[str]]]
AllowedBuilder = Callable[[Archive, Phase], list[str]]


def one(value: float, places: int = 2) -> str:
    return f"{value:.{places}f}"


def phase_games(
    archive: Archive,
    phase: Phase,
    *,
    opponent: str | None = None,
    start: date | None = None,
    end: date | None = None,
    site: str | None = None,
) -> list:
    return archive.select(
        season_type=season_type_for(phase),
        opponent=opponent,
        start=start,
        end=end,
        site=site,
    )


def team_record(games: list, label: str) -> tuple[list[str], list[str], list[str]]:
    wins, losses = record(games)
    return [f"{label} record {wins}-{losses}"], ["Knicks"], []


def team_points(games: list, label: str) -> tuple[list[str], list[str], list[str]]:
    return [f"{label} points per game {one(avg_points(games))}"], ["Knicks"], []


def team_margin(games: list, label: str) -> tuple[list[str], list[str], list[str]]:
    return [f"{label} average margin {one(avg_margin(games))}"], ["Knicks"], []


def team_opponent_points(games: list, label: str) -> tuple[list[str], list[str], list[str]]:
    return [f"{label} points allowed per game {one(avg_opponent_points(games))}"], ["Knicks"], []


def player_average(
    archive: Archive,
    player: str,
    metric: str,
    phase: Phase,
    *,
    places: int = 2,
) -> str:
    value = archive.player_avg(player, metric, season_type=season_type_for(phase))
    return one(value, places)


def player_total(
    archive: Archive, player: str, metric: str, phase: Phase, *, label: str | None = None
) -> str:
    value = archive.player_total(player, metric, season_type=season_type_for(phase))
    return f"{player} {label or metric.replace('_', ' ')} {value}"


def month_games(archive: Archive, phase: Phase, start: date, end: date) -> list:
    return phase_games(archive, phase, start=start, end=end)


def april_road_wins(archive: Archive, phase: Phase) -> int:
    return sum(
        1 for game in month_games(archive, phase, *APRIL) if not game.knicks_home and game.won
    )


def player_line(
    archive: Archive, player: str, game_id: int, fields: tuple[str, ...]
) -> tuple[list[str], list[str], list[str]]:
    line = archive.played(player, game_id)
    labels = {
        "points": "points",
        "rebounds": "rebounds",
        "assists": "assists",
        "steals": "steals",
        "blocks": "blocks",
        "minutes": "minutes",
        "plus_minus": "plus-minus",
        "three_pointers_made": "three-pointers",
    }
    facts = [f"{player} {getattr(line, field)} {labels[field]}" for field in fields]
    return facts, [player], []


def allowed_line(archive: Archive, player: str, game_id: int, fields: tuple[str, ...]) -> list[str]:
    line = archive.played(player, game_id)
    return [str(getattr(line, field)) for field in fields]


OCTOBER = (date(2025, 10, 1), date(2025, 10, 31))
APRIL = (date(2026, 4, 1), date(2026, 4, 30))
OCTOBER_NOVEMBER = (date(2025, 10, 1), date(2025, 11, 30))


@dataclass(frozen=True)
class Case:
    category: str
    question: str
    route: str | None
    answerable: bool
    facts: FactBuilder
    filters: dict[str, object]
    required_phrases: tuple[str, ...] = ()
    allowed: AllowedBuilder | None = None


EXACT: list[Case] = [
    Case(
        "exact_statistics",
        "How many games did the Bockers win in the regular season?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"regular-season wins {record(phase_games(a, phase))[0]}"],
            ["Knicks"],
            [],
        ),
        {"season_type": "regular"},
        allowed=lambda a, phase: [
            str(len(phase_games(a, phase))),
            str(record(phase_games(a, phase))[1]),
        ],
    ),
    Case(
        "exact_statistics",
        "What was their average margin overall this season?",
        "table_rag",
        True,
        lambda a, phase: team_margin(phase_games(a, phase), "overall"),
        {"season_type": "all"},
    ),
    Case(
        "exact_statistics",
        "How many road losses did they have in the regular season?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"road losses {record(phase_games(a, phase, site='away'))[1]}"],
            ["Knicks"],
            [],
        ),
        {"season_type": "regular", "site": "away"},
    ),
    Case(
        "exact_statistics",
        "How many total rebounds did Yabu grab this season?",
        "table_rag",
        True,
        lambda a, phase: (
            [player_total(a, "Guerschon Yabusele", "rebounds", phase, label="total rebounds")],
            ["Guerschon Yabusele"],
            [],
        ),
        {"player": "Guerschon Yabusele", "metric": "rebounds"},
    ),
    Case(
        "exact_statistics",
        "What was Jose Alvarado's assists average?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Jose Alvarado assists per game "
                f"{player_average(a, 'Jose Alvarado', 'assists', phase)}"
            ],
            ["Jose Alvarado"],
            [],
        ),
        {"player": "Jose Alvarado", "metric": "assists"},
    ),
    Case(
        "exact_statistics",
        "How many threes did Tyler Kolek hit?",
        "table_rag",
        True,
        lambda a, phase: (
            [player_total(a, "Tyler Kolek", "three_pointers_made", phase, label="three-pointers")],
            ["Tyler Kolek"],
            [],
        ),
        {"player": "Tyler Kolek", "metric": "three_pointers_made"},
    ),
    Case(
        "exact_statistics",
        "What was Pacôme Dadiet's scoring average?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Pacôme Dadiet points per game "
                f"{player_average(a, 'Pacôme Dadiet', 'points', phase)}"
            ],
            ["Pacôme Dadiet"],
            [],
        ),
        {"player": "Pacôme Dadiet", "metric": "points"},
    ),
    Case(
        "exact_statistics",
        "How many games did they win by 25 or more?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"wins by 25 or more {sum(1 for game in phase_games(a, phase) if game.margin >= 25)}"],
            ["Knicks"],
            [],
        ),
        {"margin": ">=25"},
    ),
    Case(
        "exact_statistics",
        "How many times did they hold opponents under 90?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "games holding opponents under 90 "
                f"{sum(1 for game in phase_games(a, phase) if game.opponent_points < 90)}"
            ],
            ["Knicks"],
            [],
        ),
        {"opponent_points": "<90"},
    ),
    Case(
        "exact_statistics",
        "What was their point differential overall?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"overall point differential {point_differential(phase_games(a, phase))}"],
            ["Knicks"],
            [],
        ),
        {"season_type": "all"},
    ),
    Case(
        "exact_statistics",
        "What was their record in games decided by 5 points or fewer?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "record in games decided by 5 or fewer "
                f"{record([game for game in phase_games(a, phase) if abs(game.margin) <= 5])[0]}-"
                f"{record([game for game in phase_games(a, phase) if abs(game.margin) <= 5])[1]}"
            ],
            ["Knicks"],
            [],
        ),
        {"margin": "<=5"},
    ),
    Case(
        "exact_statistics",
        "How many minutes did Jeremy Sochan average?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Jeremy Sochan minutes per game "
                f"{player_average(a, 'Jeremy Sochan', 'minutes', phase, places=1)}"
            ],
            ["Jeremy Sochan"],
            [],
        ),
        {"player": "Jeremy Sochan", "metric": "minutes"},
    ),
]

DATES: list[Case] = [
    Case(
        "date_range_last_n",
        "What was their record in October?",
        "table_rag",
        True,
        lambda a, phase: team_record(month_games(a, phase, *OCTOBER), "October"),
        {"month": "2025-10"},
    ),
    Case(
        "date_range_last_n",
        "How many points did they allow per game in October?",
        "table_rag",
        True,
        lambda a, phase: team_opponent_points(month_games(a, phase, *OCTOBER), "October"),
        {"month": "2025-10", "metric": "opponent_points"},
    ),
    Case(
        "date_range_last_n",
        "How many games did they play in April?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"games played in April {len(month_games(a, phase, *APRIL))}"],
            ["Knicks"],
            [],
        ),
        {"month": "2026-04"},
    ),
    Case(
        "date_range_last_n",
        "What was their record in April?",
        "table_rag",
        True,
        lambda a, phase: team_record(month_games(a, phase, *APRIL), "April"),
        {"month": "2026-04"},
    ),
    Case(
        "date_range_last_n",
        "How many road wins did they get in April?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"April road wins {april_road_wins(a, phase)}"],
            ["Knicks"],
            [],
        ),
        {"month": "2026-04", "site": "away"},
    ),
    Case(
        "date_range_last_n",
        "What was their average margin over the final 9 regular-season games?",
        "table_rag",
        True,
        lambda a, phase: team_margin(a.last(9, season_type=season_type_for(phase)), "final 9"),
        {"window": "last9_regular"},
    ),
    Case(
        "date_range_last_n",
        "What was their record over the first 9 games?",
        "table_rag",
        True,
        lambda a, phase: team_record(a.first(9, season_type=season_type_for(phase)), "first 9"),
        {"window": "first9"},
    ),
    Case(
        "date_range_last_n",
        "How many points per game did they score over their last 11 regular-season games?",
        "table_rag",
        True,
        lambda a, phase: team_points(a.last(11, season_type=season_type_for(phase)), "last 11"),
        {"window": "last11_regular"},
    ),
    Case(
        "date_range_last_n",
        "What was their record over October and November?",
        "table_rag",
        True,
        lambda a, phase: team_record(
            phase_games(a, phase, start=OCTOBER_NOVEMBER[0], end=OCTOBER_NOVEMBER[1]),
            "October and November",
        ),
        {"window": "2025-10-01..2025-11-30"},
    ),
    Case(
        "date_range_last_n",
        "How many games did they win by double digits in April?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "April wins by double digits "
                f"{sum(1 for game in month_games(a, phase, *APRIL) if game.margin >= 10)}"
            ],
            ["Knicks"],
            [],
        ),
        {"month": "2026-04", "margin": ">=10"},
    ),
    Case(
        "date_range_last_n",
        "What was their average margin in October?",
        "table_rag",
        True,
        lambda a, phase: team_margin(month_games(a, phase, *OCTOBER), "October"),
        {"month": "2025-10"},
    ),
    Case(
        "date_range_last_n",
        "How many points did they score per game versus the Grizzlies in April?",
        "table_rag",
        True,
        lambda a, phase: team_points(
            a.select(
                opponent="MEM",
                season_type=season_type_for(phase),
                start=APRIL[0],
                end=APRIL[1],
            ),
            "Memphis",
        ),
        {"opponent": "MEM", "month": "2026-04"},
    ),
]

COMPARISONS: list[Case] = [
    Case(
        "comparisons",
        "Who averaged more dimes, Tyler Kolek or Jose Alvarado?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Tyler Kolek assists per game "
                f"{player_average(a, 'Tyler Kolek', 'assists', phase)}",
                "Jose Alvarado assists per game "
                f"{player_average(a, 'Jose Alvarado', 'assists', phase)}",
            ],
            ["Tyler Kolek", "Jose Alvarado"],
            [],
        ),
        {"players": ["Tyler Kolek", "Jose Alvarado"], "metric": "assists"},
    ),
    Case(
        "comparisons",
        "Compare Yabu and Dadiet on the glass this season.",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Guerschon Yabusele rebounds per game "
                f"{player_average(a, 'Guerschon Yabusele', 'rebounds', phase)}",
                "Pacôme Dadiet rebounds per game "
                f"{player_average(a, 'Pacôme Dadiet', 'rebounds', phase)}",
            ],
            ["Guerschon Yabusele", "Pacôme Dadiet"],
            [],
        ),
        {"players": ["Guerschon Yabusele", "Pacôme Dadiet"], "metric": "rebounds"},
    ),
    Case(
        "comparisons",
        "Did they score more points per game in October or April?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                f"October points per game {one(avg_points(month_games(a, phase, *OCTOBER)))}",
                f"April points per game {one(avg_points(month_games(a, phase, *APRIL)))}",
            ],
            ["Knicks"],
            [],
        ),
        {"months": ["2025-10", "2026-04"], "metric": "points"},
    ),
    Case(
        "comparisons",
        "Compare their record in October with their April record.",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "October record "
                f"{record(month_games(a, phase, *OCTOBER))[0]}-"
                f"{record(month_games(a, phase, *OCTOBER))[1]}",
                "April record "
                f"{record(month_games(a, phase, *APRIL))[0]}-"
                f"{record(month_games(a, phase, *APRIL))[1]}",
            ],
            ["Knicks"],
            [],
        ),
        {"months": ["2025-10", "2026-04"], "metric": "record"},
    ),
    Case(
        "comparisons",
        "Which team did they score more against, Brooklyn or Indiana?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Brooklyn points per game "
                f"{one(avg_points(a.select(opponent='BKN', season_type=season_type_for(phase))))}",
                "Indiana points per game "
                f"{one(avg_points(a.select(opponent='IND', season_type=season_type_for(phase))))}",
            ],
            ["Knicks", "Brooklyn", "Indiana"],
            [],
        ),
        {"opponents": ["BKN", "IND"], "metric": "points"},
    ),
    Case(
        "comparisons",
        "Compare Kolek's and McCullar's scoring averages.",
        "table_rag",
        True,
        lambda a, phase: (
            [
                f"Tyler Kolek points per game {player_average(a, 'Tyler Kolek', 'points', phase)}",
                "Kevin McCullar Jr. points per game "
                f"{player_average(a, 'Kevin McCullar Jr.', 'points', phase)}",
            ],
            ["Tyler Kolek", "Kevin McCullar Jr."],
            [],
        ),
        {"players": ["Tyler Kolek", "Kevin McCullar Jr."], "metric": "points"},
    ),
    Case(
        "comparisons",
        "Who had the better rebounding average, Mo Diawara or Jeremy Sochan?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Mohamed Diawara rebounds per game "
                f"{player_average(a, 'Mohamed Diawara', 'rebounds', phase)}",
                "Jeremy Sochan rebounds per game "
                f"{player_average(a, 'Jeremy Sochan', 'rebounds', phase)}",
            ],
            ["Mohamed Diawara", "Jeremy Sochan"],
            [],
        ),
        {"players": ["Mohamed Diawara", "Jeremy Sochan"], "metric": "rebounds"},
    ),
    Case(
        "comparisons",
        "Compare their average margin in October and April.",
        "table_rag",
        True,
        lambda a, phase: (
            [
                f"October average margin {one(avg_margin(month_games(a, phase, *OCTOBER)))}",
                f"April average margin {one(avg_margin(month_games(a, phase, *APRIL)))}",
            ],
            ["Knicks"],
            [],
        ),
        {"months": ["2025-10", "2026-04"], "metric": "margin"},
    ),
    Case(
        "comparisons",
        "Did Yabu or Jemison play more minutes per game?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Guerschon Yabusele minutes per game "
                f"{player_average(a, 'Guerschon Yabusele', 'minutes', phase)}",
                "Trey Jemison III minutes per game "
                f"{player_average(a, 'Trey Jemison III', 'minutes', phase)}",
            ],
            ["Guerschon Yabusele", "Trey Jemison III"],
            [],
        ),
        {"players": ["Guerschon Yabusele", "Trey Jemison III"], "metric": "minutes"},
    ),
    Case(
        "comparisons",
        "Compare the Knicks' scoring average in wins and losses.",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "points per game in wins "
                f"{one(avg_points([game for game in phase_games(a, phase) if game.won]))}",
                "points per game in losses "
                f"{one(avg_points([game for game in phase_games(a, phase) if not game.won]))}",
            ],
            ["Knicks"],
            [],
        ),
        {"split": "result", "metric": "points"},
    ),
    Case(
        "comparisons",
        "Compare their point differential in October and April.",
        "table_rag",
        True,
        lambda a, phase: (
            [
                f"October point differential {point_differential(month_games(a, phase, *OCTOBER))}",
                f"April point differential {point_differential(month_games(a, phase, *APRIL))}",
            ],
            ["Knicks"],
            [],
        ),
        {"months": ["2025-10", "2026-04"], "metric": "point_differential"},
    ),
]


def question_order_digest(cases: list[Case]) -> str:
    payload = "".join(f"{case.category}\x1f{case.question}\n" for case in cases)
    return hashlib.sha256(payload.encode()).hexdigest()
