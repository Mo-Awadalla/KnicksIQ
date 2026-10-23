"""Game-specific held-out v2 questions: narratives, turning points and alias/typo asks.

All game ids and dates are disjoint from both existing evaluation files. Facts come from the
active release at generation time; no fact is entered by hand.
"""

from __future__ import annotations

import re

from app.evaluation.heldout_phase import season_type_for

from .cases import Case, allowed_line, player_average, player_line, player_total, team_record
from .facts import Archive

QUARTERS = {1: "first quarter", 2: "second quarter", 3: "third quarter", 4: "fourth quarter"}

# Fan shorthand is canonicalised before the shared phase policy runs. The policy itself is
# unchanged; this only stops a nickname from falling through to the regular-season default.
TEAM_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), canonical)
    for pattern, canonical in (
        (r"\bwiz\b", "wizards"),
        (r"\bpels\b", "pelicans"),
        (r"\bclips\b|\bclipps\b", "clippers"),
        (r"\bgrizz\b", "grizzlies"),
        (r"\bdubs\b", "warriors"),
        (r"\braps\b", "raptors"),
        (r"\bcelts\b|\bc's\b", "celtics"),
        (r"\bmavs\b", "mavericks"),
        (r"\bt-wolves\b", "timberwolves"),
        (r"\bblazers\b", "trail blazers"),
    )
)


def canonical_question(question: str) -> str:
    value = question
    for pattern, replacement in TEAM_ALIASES:
        value = pattern.sub(replacement, value)
    return value


def game_case(archive: Archive, game_id: int) -> tuple[list[str], list[str], list[str]]:
    game = archive.game(game_id)
    result = "won" if game.won else "lost"
    return (
        [
            f"final score {game.knicks_points}-{game.opponent_points}",
            f"{result} by {abs(game.margin)}",
        ],
        ["Knicks"],
        [],
    )


def allowed_game(archive: Archive, game_id: int) -> list[str]:
    game = archive.game(game_id)
    return [str(game.knicks_points), str(game.opponent_points), str(abs(game.margin))]


def quarter_case(archive: Archive, game_id: int) -> tuple[list[str], list[str], list[str]]:
    game = archive.game(game_id)
    quarter = archive.largest_quarter(game_id) if game.won else archive.worst_quarter(game_id)
    name = QUARTERS[quarter.period]
    return [f"{name} {quarter.nyk_points}-{quarter.opponent_points}"], ["Knicks"], [name]


def allowed_quarter(archive: Archive, game_id: int) -> list[str]:
    game = archive.game(game_id)
    quarter = archive.largest_quarter(game_id) if game.won else archive.worst_quarter(game_id)
    return [
        str(quarter.nyk_points),
        str(quarter.opponent_points),
        str(game.knicks_points),
        str(game.opponent_points),
    ]


def quarter_score_case(
    archive: Archive, game_id: int, period: int
) -> tuple[list[str], list[str], list[str]]:
    quarter = archive.quarter(game_id, period)
    name = QUARTERS[period]
    return [f"{name} {quarter.nyk_points}-{quarter.opponent_points}"], ["Knicks"], [name]


NARRATIVE: list[Case] = [
    Case(
        "single_game_narrative",
        "Walk me through the Bockers' blowout of Brooklyn on November 9.",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 9),
        {"game_id": 9},
        allowed=lambda a, phase: allowed_game(a, 9),
    ),
    Case(
        "single_game_narrative",
        "How did they escape Dallas on November 19?",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 14),
        {"game_id": 14},
        allowed=lambda a, phase: allowed_game(a, 14),
    ),
    Case(
        "single_game_narrative",
        "Tell me the story of the Jazz rout on December 5.",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 22),
        {"game_id": 22},
        allowed=lambda a, phase: allowed_game(a, 22),
    ),
    Case(
        "single_game_narrative",
        "How did they take down the Magic in Orlando on December 13?",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 25),
        {"game_id": 25},
        allowed=lambda a, phase: allowed_game(a, 25),
    ),
    Case(
        "single_game_narrative",
        "What happened in New Orleans on December 29?",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 32),
        {"game_id": 32},
        allowed=lambda a, phase: allowed_game(a, 32),
    ),
    Case(
        "single_game_narrative",
        "Break down the Clippers win on January 7.",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 37),
        {"game_id": 37},
        allowed=lambda a, phase: allowed_game(a, 37),
    ),
    Case(
        "single_game_narrative",
        "How did they handle Portland on January 11?",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 39),
        {"game_id": 39},
        allowed=lambda a, phase: allowed_game(a, 39),
    ),
    Case(
        "single_game_narrative",
        "Describe the Nets beatdown on January 21.",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 44),
        {"game_id": 44},
        allowed=lambda a, phase: allowed_game(a, 44),
    ),
    Case(
        "single_game_narrative",
        "What went wrong in the Pacers overtime loss on February 10?",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 54),
        {"game_id": 54},
        allowed=lambda a, phase: allowed_game(a, 54),
    ),
    Case(
        "single_game_narrative",
        "How did they edge Houston on February 21?",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 57),
        {"game_id": 57},
        allowed=lambda a, phase: allowed_game(a, 57),
    ),
    Case(
        "single_game_narrative",
        "What happened in Memphis on April 1?",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 77),
        {"game_id": 77},
        allowed=lambda a, phase: allowed_game(a, 77),
    ),
]

TURNING: list[Case] = [
    Case(
        "turning_points",
        "Which quarter swung the two-point win in Dallas on November 19?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_case(a, 14),
        {"game_id": 14},
        allowed=lambda a, phase: allowed_quarter(a, 14),
    ),
    Case(
        "turning_points",
        "Where did the Orlando game turn on November 22?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_case(a, 15),
        {"game_id": 15},
        allowed=lambda a, phase: allowed_quarter(a, 15),
    ),
    Case(
        "turning_points",
        "Which quarter broke open the Orlando win on December 13?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_case(a, 25),
        {"game_id": 25},
        allowed=lambda a, phase: allowed_quarter(a, 25),
    ),
    Case(
        "turning_points",
        "Where did the Portland game turn on January 11?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_case(a, 39),
        {"game_id": 39},
        allowed=lambda a, phase: allowed_quarter(a, 39),
    ),
    Case(
        "turning_points",
        "Which quarter cost them against Phoenix on January 17?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_case(a, 42),
        {"game_id": 42},
        allowed=lambda a, phase: allowed_quarter(a, 42),
    ),
    Case(
        "turning_points",
        "When did the Dallas rematch get away on January 19?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_case(a, 43),
        {"game_id": 43},
        allowed=lambda a, phase: allowed_quarter(a, 43),
    ),
    Case(
        "turning_points",
        "Which quarter broke open the Washington game on February 3?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_case(a, 50),
        {"game_id": 50},
        allowed=lambda a, phase: allowed_quarter(a, 50),
    ),
    Case(
        "turning_points",
        "Which quarter decided the Pacers overtime game on February 10?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_case(a, 54),
        {"game_id": 54},
        allowed=lambda a, phase: allowed_quarter(a, 54),
    ),
    Case(
        "turning_points",
        "Where did the Utah game turn on March 11?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_case(a, 67),
        {"game_id": 67},
        allowed=lambda a, phase: allowed_quarter(a, 67),
    ),
    Case(
        "turning_points",
        "Which quarter put the Indiana game away on March 13?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_case(a, 68),
        {"game_id": 68},
        allowed=lambda a, phase: allowed_quarter(a, 68),
    ),
    Case(
        "turning_points",
        "Which quarter decided the Brooklyn squeaker on March 20?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_case(a, 71),
        {"game_id": 71},
        allowed=lambda a, phase: allowed_quarter(a, 71),
    ),
]

ALIASES: list[Case] = [
    Case(
        "aliases_typos",
        "How did the Bockers do aginst the Nets this year?",
        "retrieval_rag",
        True,
        lambda a, phase: team_record(
            a.select(opponent="BKN", season_type=season_type_for(phase)), "Brooklyn"
        ),
        {"opponent": "BKN"},
    ),
    Case(
        "aliases_typos",
        "What's NY's record v the Wizards?",
        "retrieval_rag",
        True,
        lambda a, phase: team_record(
            a.select(opponent="WAS", season_type=season_type_for(phase)), "Washington"
        ),
        {"opponent": "WAS"},
    ),
    Case(
        "aliases_typos",
        "How many boards did Yabu pull down?",
        "retrieval_rag",
        True,
        lambda a, phase: (
            [player_total(a, "Guerschon Yabusele", "rebounds", phase, label="total rebounds")],
            ["Guerschon Yabusele"],
            [],
        ),
        {"player": "Guerschon Yabusele", "metric": "rebounds"},
    ),
    Case(
        "aliases_typos",
        "What did Kolek average in dimes?",
        "retrieval_rag",
        True,
        lambda a, phase: (
            [f"Tyler Kolek assists per game {player_average(a, 'Tyler Kolek', 'assists', phase)}"],
            ["Tyler Kolek"],
            [],
        ),
        {"player": "Tyler Kolek", "metric": "assists"},
    ),
    Case(
        "aliases_typos",
        "How did the Knics look against Minnesota?",
        "retrieval_rag",
        True,
        lambda a, phase: team_record(
            a.select(opponent="MIN", season_type=season_type_for(phase)), "Minnesota"
        ),
        {"opponent": "MIN"},
    ),
    Case(
        "aliases_typos",
        "Tell me about Yabu's night in Salt Lake on December 5.",
        "retrieval_rag",
        True,
        lambda a, phase: player_line(a, "Guerschon Yabusele", 22, ("points", "rebounds")),
        {"game_id": 22, "player": "Guerschon Yabusele"},
        allowed=lambda a, phase: (
            allowed_line(a, "Guerschon Yabusele", 22, ("points", "rebounds")) + allowed_game(a, 22)
        ),
    ),
    Case(
        "aliases_typos",
        "What happened in the fourth against the Pels on December 29?",
        "retrieval_rag",
        True,
        lambda a, phase: quarter_score_case(a, 32, 4),
        {"game_id": 32},
        allowed=lambda a, phase: [
            str(a.quarter(32, 4).nyk_points),
            str(a.quarter(32, 4).opponent_points),
            str(a.game(32).knicks_points),
            str(a.game(32).opponent_points),
        ],
    ),
    Case(
        "aliases_typos",
        "What did Yabu do versus the Clips on January 7?",
        "retrieval_rag",
        True,
        lambda a, phase: player_line(a, "Guerschon Yabusele", 37, ("points", "rebounds")),
        {"game_id": 37, "player": "Guerschon Yabusele"},
        allowed=lambda a, phase: (
            allowed_line(a, "Guerschon Yabusele", 37, ("points", "rebounds")) + allowed_game(a, 37)
        ),
    ),
    Case(
        "aliases_typos",
        "What was the score against the Grizz on April 1?",
        "retrieval_rag",
        True,
        lambda a, phase: game_case(a, 77),
        {"game_id": 77},
        allowed=lambda a, phase: allowed_game(a, 77),
    ),
    Case(
        "aliases_typos",
        "How did they do versus the Magic?",
        "retrieval_rag",
        True,
        lambda a, phase: team_record(
            a.select(opponent="ORL", season_type=season_type_for(phase)), "Orlando"
        ),
        {"opponent": "ORL"},
    ),
    Case(
        "aliases_typos",
        "How many points did Alvarado drop in Houston on February 21?",
        "retrieval_rag",
        True,
        lambda a, phase: player_line(a, "Jose Alvarado", 57, ("points",)),
        {"game_id": 57, "player": "Jose Alvarado"},
        allowed=lambda a, phase: (
            allowed_line(a, "Jose Alvarado", 57, ("points",)) + allowed_game(a, 57)
        ),
    ),
]
