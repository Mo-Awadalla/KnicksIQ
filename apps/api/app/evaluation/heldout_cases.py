"""Held-out analyst questions and their database-computed fact builders.

Every fact comes from the active release at generation time. Never edit a fact by hand.
The season phase is resolved from the question text by the policy table below; a fact
builder receives that phase and never sees a response.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.evaluation.heldout_facts import (
    Archive,
    avg_margin,
    avg_opponent_points,
    avg_points,
    record,
)
from app.evaluation.heldout_phase import Phase, phase_games, season_type_for

FactBuilder = Callable[[Archive, Phase], tuple[list[str], list[str], list[str]]]

# The order in this file determines the generated ids. The digest stops a question text or
# an order change from silently producing a different set; updating it is a visible diff.
QUESTION_ORDER_SHA256 = "132b99959e58aaffe17cc9759df04a1ca91639a2c45a92863529ba09dcdbb697"


def question_order_digest(cases: list[Case]) -> str:
    payload = "".join(f"{case.category}\x1f{case.question}\n" for case in cases)
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class Case:
    category: str
    question: str
    route: str | None
    answerable: bool
    facts: FactBuilder
    filters: dict[str, object]
    required_phrases: tuple[str, ...] = ()


def one(value: float, places: int = 1) -> str:
    return f"{value:.{places}f}"


def player_avg(
    archive: Archive,
    player: str,
    metric: str,
    phase: Phase,
    *,
    places: int = 2,
    opponent: str | None = None,
    window: int | None = None,
    season_type: str | None = None,
) -> str:
    """A phase-scoped player average over observed appearances, formatted for a fact."""
    season = season_type if season_type is not None else season_type_for(phase)
    games = None
    if window is not None:
        games = archive.last(window, season_type=season)
    if opponent is not None:
        games = archive.select(opponent=opponent, season_type=season)
    return one(archive.player_avg(player, metric, season_type=season, games=games), places)


def player_total(archive: Archive, player: str, metric: str, phase: Phase) -> int:
    return archive.player_total(player, metric, season_type=season_type_for(phase))


def opponent_points(archive: Archive, opponent: str, phase: Phase) -> str:
    games = archive.select(opponent=opponent, season_type=season_type_for(phase))
    return one(avg_points(games), 2)


def january_road_wins(archive: Archive, phase: Phase) -> int:
    games = phase_games(archive, phase, start=date(2026, 1, 1), end=date(2026, 1, 31), site="away")
    return record(games)[0]


def quarter_text(
    archive: Archive, game_id: int, *, worst: bool = False
) -> tuple[str, list[str], list[str]]:
    quarter = archive.worst_quarter(game_id) if worst else archive.largest_quarter(game_id)
    names = {1: "first quarter", 2: "second quarter", 3: "third quarter", 4: "fourth quarter"}
    phrase = names[quarter.period]
    return (
        f"{phrase} {quarter.nyk_points}-{quarter.opponent_points}",
        [phrase],
        [],
    )


def game_case(
    archive: Archive, game_id: int, include_top: bool = True
) -> tuple[list[str], list[str], list[str]]:
    game = archive.game(game_id)
    facts = [f"final score {game.knicks_points}-{game.opponent_points}"]
    phrases = []
    if include_top:
        top = archive.top_scorer(game_id)
        facts.append(f"{top.player} {top.points} points")
    return facts, ["Knicks"], phrases


def team_case(archive: Archive, games: list, label: str) -> tuple[list[str], list[str], list[str]]:
    wins, losses = record(games)
    return [f"{label} record {wins}-{losses}"], ["Knicks"], []


CASES: list[Case] = [
    # exact_statistics
    Case(
        "exact_statistics",
        "What was the Knicks' regular-season record?",
        "table_rag",
        True,
        lambda a, phase: team_case(a, phase_games(a, phase), "regular-season"),
        {"season_type": "regular"},
    ),
    Case(
        "exact_statistics",
        "How many points per game did New York average for the full season?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"points per game {one(avg_points(phase_games(a, phase)), 2)}"],
            ["Knicks"],
            [],
        ),
        {"window": "season"},
    ),
    Case(
        "exact_statistics",
        "What was the Knicks' average margin in the regular season?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"average margin {one(avg_margin(phase_games(a, phase)), 2)}"],
            ["Knicks"],
            [],
        ),
        {"season_type": "regular"},
    ),
    Case(
        "exact_statistics",
        "How many home games did the Knicks lose?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"home losses {record(phase_games(a, phase, site='home'))[1]}"],
            ["Knicks"],
            [],
        ),
        {"site": "home"},
    ),
    Case(
        "exact_statistics",
        "How many total rebounds did Mitchell Robinson grab?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Mitchell Robinson total rebounds "
                f"{player_total(a, 'Mitchell Robinson', 'rebounds', phase)}"
            ],
            ["Mitchell Robinson"],
            [],
        ),
        {"player": "Mitchell Robinson", "metric": "rebounds"},
    ),
    Case(
        "exact_statistics",
        "What was Miles McBride's assists average?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Miles McBride assists per game "
                f"{player_avg(a, 'Miles McBride', 'assists', phase, places=1)}"
            ],
            ["Miles McBride"],
            [],
        ),
        {"player": "Miles McBride", "metric": "assists"},
    ),
    Case(
        "exact_statistics",
        "How many three-pointers did Landry Shamet make this season?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Landry Shamet three-pointers made "
                f"{player_total(a, 'Landry Shamet', 'three_pointers_made', phase)}"
            ],
            ["Landry Shamet"],
            [],
        ),
        {"player": "Landry Shamet", "metric": "three_pointers_made"},
    ),
    Case(
        "exact_statistics",
        "What was Jordan Clarkson's scoring average?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Jordan Clarkson points per game "
                f"{player_avg(a, 'Jordan Clarkson', 'points', phase, places=1)}"
            ],
            ["Jordan Clarkson"],
            [],
        ),
        {"player": "Jordan Clarkson", "metric": "points"},
    ),
    Case(
        "exact_statistics",
        "How many games did the Knicks win by at least 20 points?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"wins by 20 or more {sum(1 for g in phase_games(a, phase) if g.margin >= 20)}"],
            ["Knicks"],
            [],
        ),
        {"margin": ">=20"},
    ),
    # date_range_last_n
    Case(
        "date_range_last_n",
        "What was the Knicks' record over their final 8 regular-season games?",
        "table_rag",
        True,
        lambda a, phase: team_case(
            a, a.last(8, season_type=season_type_for(phase)), "final 8 regular-season"
        ),
        {"window": "last8_regular"},
    ),
    Case(
        "date_range_last_n",
        "How many points did the Knicks allow per game in February?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "points allowed per game "
                + one(
                    avg_opponent_points(
                        phase_games(a, phase, start=date(2026, 2, 1), end=date(2026, 2, 28))
                    ),
                    2,
                )
            ],
            ["Knicks"],
            [],
        ),
        {"month": "2026-02"},
    ),
    Case(
        "date_range_last_n",
        "What was the Knicks' record in March?",
        "table_rag",
        True,
        lambda a, phase: team_case(
            a, phase_games(a, phase, start=date(2026, 3, 1), end=date(2026, 3, 31)), "March"
        ),
        {"month": "2026-03"},
    ),
    Case(
        "date_range_last_n",
        "How many road games did the Knicks win in January?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"January road wins {january_road_wins(a, phase)}"],
            ["Knicks"],
            [],
        ),
        {"month": "2026-01", "site": "away"},
    ),
    Case(
        "date_range_last_n",
        "What was Mitchell Robinson's rebounding average over his last 6 appearances?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Mitchell Robinson rebounds per game "
                f"{player_avg(a, 'Mitchell Robinson', 'rebounds', phase, window=6)}"
            ],
            ["Mitchell Robinson"],
            [],
        ),
        {"player": "Mitchell Robinson", "window": "last6"},
    ),
    Case(
        "date_range_last_n",
        "What was Miles McBride's scoring average in the 2025-26 playoffs?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Miles McBride playoff points per game "
                f"{player_avg(a, 'Miles McBride', 'points', phase)}"
            ],
            ["Miles McBride"],
            [],
        ),
        {"season_type": "playoffs", "player": "Miles McBride"},
    ),
    Case(
        "date_range_last_n",
        "How many games did the Knicks play in November?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "games played in November "
                f"{len(phase_games(a, phase, start=date(2025, 11, 1), end=date(2025, 11, 30)))}"
            ],
            ["Knicks"],
            [],
        ),
        {"month": "2025-11"},
    ),
    Case(
        "date_range_last_n",
        "What was the Knicks' record over their first 15 games?",
        "table_rag",
        True,
        lambda a, phase: team_case(a, a.first(15, season_type=season_type_for(phase)), "first 15"),
        {"window": "first15_regular"},
    ),
    Case(
        "date_range_last_n",
        "What was the Knicks' average margin over their last 7 games?",
        "table_rag",
        True,
        lambda a, phase: (
            [f"average margin {one(avg_margin(a.last(7, season_type=season_type_for(phase))), 2)}"],
            ["Knicks"],
            [],
        ),
        {"window": "last7"},
    ),
    # comparisons
    Case(
        "comparisons",
        "Who averaged more points per game this season, Miles McBride or Landry Shamet?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                f"Miles McBride points per game {player_avg(a, 'Miles McBride', 'points', phase)}",
                f"Landry Shamet points per game {player_avg(a, 'Landry Shamet', 'points', phase)}",
            ],
            ["Miles McBride", "Landry Shamet"],
            [],
        ),
        {"players": ["Miles McBride", "Landry Shamet"], "metric": "points"},
    ),
    Case(
        "comparisons",
        "Compare Mitchell Robinson and Ariel Hukporti as rebounders this season.",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Mitchell Robinson rebounds per game "
                f"{player_avg(a, 'Mitchell Robinson', 'rebounds', phase)}",
                "Ariel Hukporti rebounds per game "
                f"{player_avg(a, 'Ariel Hukporti', 'rebounds', phase)}",
            ],
            ["Mitchell Robinson", "Ariel Hukporti"],
            [],
        ),
        {"players": ["Mitchell Robinson", "Ariel Hukporti"], "metric": "rebounds"},
    ),
    Case(
        "comparisons",
        "Did the Knicks score more points per game at home or on the road?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                f"home points per game {one(avg_points(phase_games(a, phase, site='home')), 2)}",
                f"road points per game {one(avg_points(phase_games(a, phase, site='away')), 2)}",
            ],
            ["Knicks"],
            [],
        ),
        {"site": ["home", "away"]},
    ),
    Case(
        "comparisons",
        "Compare the Knicks' regular-season and playoff records.",
        "table_rag",
        True,
        lambda a, phase: (
            [
                f"regular-season record {record(a.select(season_type='regular'))[0]}-"
                f"{record(a.select(season_type='regular'))[1]}",
                f"playoff record {record(a.select(season_type='playoffs'))[0]}-"
                f"{record(a.select(season_type='playoffs'))[1]}",
            ],
            ["Knicks"],
            [],
        ),
        {"season_types": ["regular", "playoffs"]},
    ),
    Case(
        "comparisons",
        "Who had the higher assists average, Miles McBride or Landry Shamet?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Miles McBride assists per game "
                f"{player_avg(a, 'Miles McBride', 'assists', phase)}",
                "Landry Shamet assists per game "
                f"{player_avg(a, 'Landry Shamet', 'assists', phase)}",
            ],
            ["Miles McBride", "Landry Shamet"],
            [],
        ),
        {"players": ["Miles McBride", "Landry Shamet"], "metric": "assists"},
    ),
    Case(
        "comparisons",
        "Compare Jordan Clarkson's regular-season and playoff scoring averages.",
        "table_rag",
        True,
        lambda a, phase: (
            [
                "Jordan Clarkson regular-season points per game "
                f"{player_avg(a, 'Jordan Clarkson', 'points', phase, season_type='regular')}",
                "Jordan Clarkson playoff points per game "
                f"{player_avg(a, 'Jordan Clarkson', 'points', phase, season_type='playoffs')}",
            ],
            ["Jordan Clarkson"],
            [],
        ),
        {"player": "Jordan Clarkson", "season_types": ["regular", "playoffs"]},
    ),
    Case(
        "comparisons",
        "Compare the Knicks' average margin at home and on the road.",
        "table_rag",
        True,
        lambda a, phase: (
            [
                f"home average margin {one(avg_margin(phase_games(a, phase, site='home')), 2)}",
                f"road average margin {one(avg_margin(phase_games(a, phase, site='away')), 2)}",
            ],
            ["Knicks"],
            [],
        ),
        {"site": ["home", "away"]},
    ),
    Case(
        "comparisons",
        "Which opponent did the Knicks score more points per game against, Detroit or Cleveland?",
        "table_rag",
        True,
        lambda a, phase: (
            [
                f"Detroit points per game {opponent_points(a, 'DET', phase)}",
                f"Cleveland points per game {opponent_points(a, 'CLE', phase)}",
            ],
            ["Knicks", "Detroit", "Cleveland"],
            [],
        ),
        {"opponents": ["DET", "CLE"]},
    ),
]


def _narrative_cases() -> list[Case]:
    games = [
        (28, "Walk me through the Knicks' home win over Miami on December 21."),
        (101, "How did the Knicks win Game 5 of the Finals against San Antonio on June 13?"),
        (96, "Tell the story of the Knicks' road win in Cleveland on May 25."),
        (92, "What decided the Knicks' playoff win over Philadelphia on May 10?"),
        (52, "How did the Knicks lose at Detroit on February 6?"),
        (60, "Describe the Knicks' win over Milwaukee on February 27."),
        (64, "What happened in the Knicks' game at Denver on March 6?"),
        (49, "Walk me through the Knicks' win over the Lakers on February 1."),
    ]
    cases = []
    for game_id, question in games:
        cases.append(
            Case(
                "single_game_narrative",
                question,
                "retrieval_rag",
                True,
                lambda a, phase, game_id=game_id: game_case(a, game_id),
                {"game_id": game_id},
            )
        )
    return cases


def _turning_cases() -> list[Case]:
    games = [
        (28, "Which quarter swung the Knicks' December 21 win over Miami?"),
        (101, "Where did the Knicks' Game 5 win over San Antonio turn?"),
        (96, "Which quarter broke open the Knicks' May 25 win at Cleveland?"),
        (92, "When did the Knicks pull away from Philadelphia on May 10?"),
        (52, "Which quarter decided the Knicks' February 6 loss at Detroit?"),
        (60, "Which quarter broke open the Knicks' February 27 win at Milwaukee?"),
        (64, "Which quarter put the Knicks' March 6 game at Denver out of reach?"),
        (49, "Where did the Knicks' February 1 win over the Lakers turn?"),
    ]
    cases = []
    for game_id, question in games:

        def facts(
            archive: Archive, phase: Phase, game_id: int = game_id
        ) -> tuple[list[str], list[str], list[str]]:
            fact, phrases, _ = quarter_text(archive, game_id, worst=game_id == 52)
            return [fact], ["Knicks"], phrases

        cases.append(
            Case(
                "turning_points",
                question,
                "retrieval_rag",
                True,
                facts,
                {"game_id": game_id},
            )
        )
    return cases
