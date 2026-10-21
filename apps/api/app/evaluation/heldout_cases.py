"""Held-out analyst questions and their database-computed fact builders.

Every fact comes from the active release at generation time. Never edit a fact by hand.
"""

from __future__ import annotations

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

FactBuilder = Callable[[Archive], tuple[list[str], list[str], list[str]]]


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


def player_avg(archive: Archive, player: str, metric: str, **kwargs) -> str:
    return one(archive.player_avg(player, metric, **kwargs), 2)


def games_vs(archive: Archive, opponent: str, season_type: str | None = None) -> list:
    return archive.select(opponent=opponent, season_type=season_type)


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
        lambda a: team_case(a, a.select(season_type="regular"), "regular-season"),
        {"season_type": "regular"},
    ),
    Case(
        "exact_statistics",
        "How many points per game did New York average for the full season?",
        "table_rag",
        True,
        lambda a: ([f"points per game {one(avg_points(a.select()), 2)}"], ["Knicks"], []),
        {"window": "season"},
    ),
    Case(
        "exact_statistics",
        "What was the Knicks' average margin in the regular season?",
        "table_rag",
        True,
        lambda a: (
            [f"average margin {one(avg_margin(a.select(season_type='regular')), 2)}"],
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
        lambda a: ([f"home losses {record(a.select(site='home'))[1]}"], ["Knicks"], []),
        {"site": "home"},
    ),
    Case(
        "exact_statistics",
        "How many total rebounds did Mitchell Robinson grab?",
        "table_rag",
        True,
        lambda a: (
            [f"Mitchell Robinson total rebounds {a.player_total('Mitchell Robinson', 'rebounds')}"],
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
        lambda a: (
            [f"Miles McBride assists per game {one(a.player_avg('Miles McBride', 'assists'))}"],
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
        lambda a: (
            [
                "Landry Shamet three-pointers made "
                f"{a.player_total('Landry Shamet', 'three_pointers_made')}"
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
        lambda a: (
            [f"Jordan Clarkson points per game {one(a.player_avg('Jordan Clarkson', 'points'))}"],
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
        lambda a: (
            [f"wins by 20 or more {sum(1 for g in a.games if g.margin >= 20)}"],
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
        lambda a: team_case(a, a.last(8, season_type="regular"), "final 8 regular-season"),
        {"window": "last8_regular"},
    ),
    Case(
        "date_range_last_n",
        "How many points did the Knicks allow per game in February?",
        "table_rag",
        True,
        lambda a: (
            [
                "points allowed per game "
                + one(
                    avg_opponent_points(a.select(start=date(2026, 2, 1), end=date(2026, 2, 28))), 2
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
        lambda a: team_case(a, a.select(start=date(2026, 3, 1), end=date(2026, 3, 31)), "March"),
        {"month": "2026-03"},
    ),
    Case(
        "date_range_last_n",
        "How many road games did the Knicks win in January?",
        "table_rag",
        True,
        lambda a: (
            [
                "January road wins "
                f"{record(a.select(start=date(2026, 1, 1), end=date(2026, 1, 31), site='away'))[0]}"
            ],
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
        lambda a: (
            [
                "Mitchell Robinson rebounds per game "
                f"{one(a.player_avg('Mitchell Robinson', 'rebounds', games=a.last(6)), 2)}"
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
        lambda a: (
            [
                "Miles McBride playoff points per game "
                f"{one(a.player_avg('Miles McBride', 'points', season_type='playoffs'), 2)}"
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
        lambda a: (
            [
                "games played in November "
                f"{len(a.select(start=date(2025, 11, 1), end=date(2025, 11, 30)))}"
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
        lambda a: team_case(a, a.first(15, season_type="regular"), "first 15"),
        {"window": "first15_regular"},
    ),
    Case(
        "date_range_last_n",
        "What was the Knicks' average margin over their last 7 games?",
        "table_rag",
        True,
        lambda a: (
            [f"average margin {one(avg_margin(a.last(7)), 2)}"],
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
        lambda a: (
            [
                f"Miles McBride points per game {one(a.player_avg('Miles McBride', 'points'), 2)}",
                f"Landry Shamet points per game {one(a.player_avg('Landry Shamet', 'points'), 2)}",
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
        lambda a: (
            [
                "Mitchell Robinson rebounds per game "
                f"{one(a.player_avg('Mitchell Robinson', 'rebounds'), 2)}",
                "Ariel Hukporti rebounds per game "
                f"{one(a.player_avg('Ariel Hukporti', 'rebounds'), 2)}",
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
        lambda a: (
            [
                f"home points per game {one(avg_points(a.select(site='home')), 2)}",
                f"road points per game {one(avg_points(a.select(site='away')), 2)}",
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
        lambda a: (
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
        lambda a: (
            [
                "Miles McBride assists per game "
                f"{one(a.player_avg('Miles McBride', 'assists'), 2)}",
                "Landry Shamet assists per game "
                f"{one(a.player_avg('Landry Shamet', 'assists'), 2)}",
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
        lambda a: (
            [
                "Jordan Clarkson regular-season points per game "
                f"{one(a.player_avg('Jordan Clarkson', 'points', season_type='regular'), 2)}",
                "Jordan Clarkson playoff points per game "
                f"{one(a.player_avg('Jordan Clarkson', 'points', season_type='playoffs'), 2)}",
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
        lambda a: (
            [
                f"home average margin {one(avg_margin(a.select(site='home')), 2)}",
                f"road average margin {one(avg_margin(a.select(site='away')), 2)}",
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
        lambda a: (
            [
                f"Detroit points per game {one(avg_points(a.select(opponent='DET')), 2)}",
                f"Cleveland points per game {one(avg_points(a.select(opponent='CLE')), 2)}",
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
                lambda a, game_id=game_id: game_case(a, game_id),
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
            archive: Archive, game_id: int = game_id
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


ALIASES = [
    (
        "What was the Knickerbockers' record against the Heat in the regular season?",
        lambda a: team_case(a, a.select(opponent="MIA", season_type="regular"), "Heat"),
        {"opponent": "MIA"},
    ),
    (
        "How did NYK fare aginst Cleveland this season?",
        lambda a: team_case(a, a.select(opponent="CLE"), "Cleveland"),
        {"opponent": "CLE"},
    ),
    (
        "What did Mitch Rob average on the glass versus the Sixers?",
        lambda a: (
            [
                "Mitchell Robinson rebounds per game "
                f"{player_avg(a, 'Mitchell Robinson', 'rebounds', games=games_vs(a, 'PHI'))}"
            ],
            ["Mitchell Robinson"],
            [],
        ),
        {"player": "Mitchell Robinson", "opponent": "PHI"},
    ),
    (
        "How did Shamet score against the Spurs in the playoffs?",
        lambda a: (
            [
                "Landry Shamet points per game "
                f"{player_avg(a, 'Landry Shamet', 'points', games=games_vs(a, 'SAS', 'playoffs'))}"
            ],
            ["Landry Shamet"],
            [],
        ),
        {"player": "Landry Shamet", "opponent": "SAS"},
    ),
    (
        "How many points did the Knicks score per game v PHI?",
        lambda a: (
            [f"points per game {one(avg_points(a.select(opponent='PHI')), 2)}"],
            ["Knicks"],
            [],
        ),
        {"opponent": "PHI"},
    ),
    (
        "How did Mitch Rob play against Detroit on February 6?",
        lambda a: (
            [
                f"Mitchell Robinson {a.line('Mitchell Robinson', 52).points} points",
                f"Mitchell Robinson {a.line('Mitchell Robinson', 52).rebounds} rebounds",
            ],
            ["Mitchell Robinson"],
            [],
        ),
        {"player": "Mitchell Robinson", "game_id": 52},
    ),
    (
        "What was the Knicks' result versus the Cavs on February 24?",
        lambda a: (
            [f"final score {a.game(59).knicks_points}-{a.game(59).opponent_points}"],
            ["Knicks"],
            [],
        ),
        {"game_id": 59},
    ),
    (
        "How did the Knicks do against the Thunder?",
        lambda a: team_case(a, a.select(opponent="OKC"), "Oklahoma City"),
        {"opponent": "OKC"},
    ),
]

UNSUPPORTED = [
    "What is the betting spread for the Knicks' next game?",
    "Is Miles McBride playing tonight?",
    "Will the Knicks repeat as champions next season?",
    "What seed will the Knicks get in 2026-27?",
    "Who won the Knicks game last night?",
    "What are the current Eastern Conference standings?",
    "Should the Knicks trade for another center?",
    "What was the score of the 1994 NBA Finals?",
    "How many points will Brunson score tomorrow?",
    "What does today's injury report say about Landry Shamet?",
]
