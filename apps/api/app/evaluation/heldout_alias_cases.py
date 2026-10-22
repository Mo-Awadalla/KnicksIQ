"""Alias, typo and unsupported cases for the held-out analyst evaluation set."""

from __future__ import annotations

from app.evaluation.heldout_cases import opponent_points, player_avg, team_case
from app.evaluation.heldout_phase import season_type_for

ALIASES = [
    (
        "What was the Knickerbockers' record against the Heat in the regular season?",
        lambda a, phase: team_case(
            a, a.select(opponent="MIA", season_type=season_type_for(phase)), "Heat"
        ),
        {"opponent": "MIA"},
    ),
    (
        "How did NYK fare aginst Cleveland this season?",
        lambda a, phase: team_case(
            a, a.select(opponent="CLE", season_type=season_type_for(phase)), "Cleveland"
        ),
        {"opponent": "CLE"},
    ),
    (
        "What did Mitch Rob average on the glass versus the Sixers?",
        lambda a, phase: (
            [
                "Mitchell Robinson rebounds per game "
                f"{player_avg(a, 'Mitchell Robinson', 'rebounds', phase, opponent='PHI')}"
            ],
            ["Mitchell Robinson"],
            [],
        ),
        {"player": "Mitchell Robinson", "opponent": "PHI"},
    ),
    (
        "How did Shamet score against the Spurs in the playoffs?",
        lambda a, phase: (
            [
                "Landry Shamet points per game "
                f"{player_avg(a, 'Landry Shamet', 'points', phase, opponent='SAS')}"
            ],
            ["Landry Shamet"],
            [],
        ),
        {"player": "Landry Shamet", "opponent": "SAS"},
    ),
    (
        "How many points did the Knicks score per game v PHI?",
        lambda a, phase: (
            [f"points per game {opponent_points(a, 'PHI', phase)}"],
            ["Knicks"],
            [],
        ),
        {"opponent": "PHI"},
    ),
    (
        "How did Mitch Rob play against Detroit on February 6?",
        lambda a, phase: (
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
        lambda a, phase: (
            [f"final score {a.game(59).knicks_points}-{a.game(59).opponent_points}"],
            ["Knicks"],
            [],
        ),
        {"game_id": 59},
    ),
    (
        "How did the Knicks do against the Thunder?",
        lambda a, phase: team_case(
            a, a.select(opponent="OKC", season_type=season_type_for(phase)), "Oklahoma City"
        ),
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
