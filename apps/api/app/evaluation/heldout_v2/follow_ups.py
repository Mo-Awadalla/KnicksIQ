"""Ten two-turn held-out v2 follow-up sessions.

Turn one establishes a game in context; turn two is the scored follow-up. The first-turn
assistant answer is generated from the same archive as the facts, so the context never contains
an invented score.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from app.evaluation.heldout_phase import Phase

from .cases import allowed_line, player_line
from .cases_games import (
    allowed_game,
    allowed_quarter,
    quarter_case,
    quarter_score_case,
)
from .facts import Archive

AllowedBuilder = Callable[[Archive, Phase], list[str]]


@dataclass(frozen=True)
class FollowUpSession:
    first_question: str
    game_id: int
    follow_up: str
    facts: Callable[[Archive, Phase], tuple[list[str], list[str], list[str]]]
    allowed: AllowedBuilder | None = None


def _margin(archive: Archive, game_id: int) -> tuple[list[str], list[str], list[str]]:
    game = archive.game(game_id)
    return [f"margin {abs(game.margin)}"], ["Knicks"], []


def _team_three(archive: Archive, game_id: int) -> tuple[list[str], list[str], list[str]]:
    line = archive.team_line(game_id)
    return [f"team three-pointers made {line.three_pointers_made}"], ["Knicks"], []


def _team_rebounds(archive: Archive, game_id: int) -> tuple[list[str], list[str], list[str]]:
    line = archive.team_line(game_id)
    return [f"team rebounds {line.rebounds}"], ["Knicks"], []


FOLLOW_UP_SESSIONS: list[FollowUpSession] = [
    FollowUpSession(
        "How did the Bockers do against Brooklyn on November 9?",
        9,
        "How big was the margin?",
        lambda a, phase: _margin(a, 9),
        lambda a, phase: allowed_game(a, 9),
    ),
    FollowUpSession(
        "What happened in Orlando on November 22?",
        15,
        "What was the fourth-quarter score?",
        lambda a, phase: quarter_score_case(a, 15, 4),
        lambda a, phase: [
            str(a.quarter(15, 4).nyk_points),
            str(a.quarter(15, 4).opponent_points),
            str(a.game(15).knicks_points),
            str(a.game(15).opponent_points),
        ],
    ),
    FollowUpSession(
        "How did the Jazz game go on December 5?",
        22,
        "How many threes did they hit?",
        lambda a, phase: _team_three(a, 22),
        lambda a, phase: [str(a.team_line(22).three_pointers_made)],
    ),
    FollowUpSession(
        "What was the result in Minnesota on December 23?",
        29,
        "How many rebounds did they pull down?",
        lambda a, phase: _team_rebounds(a, 29),
        lambda a, phase: [str(a.team_line(29).rebounds)],
    ),
    FollowUpSession(
        "What happened in New Orleans on December 29?",
        32,
        "Which quarter hurt them most?",
        lambda a, phase: quarter_score_case(a, 32, 3),
        lambda a, phase: [
            str(a.quarter(32, 3).nyk_points),
            str(a.quarter(32, 3).opponent_points),
        ],
    ),
    FollowUpSession(
        "How did the Clippers game go on January 7?",
        37,
        "How many dimes did Kolek have?",
        lambda a, phase: player_line(a, "Tyler Kolek", 37, ("assists",)),
        lambda a, phase: allowed_line(a, "Tyler Kolek", 37, ("assists",)),
    ),
    FollowUpSession(
        "What happened in Sacramento on January 14?",
        40,
        "How many boards did Yabu grab?",
        lambda a, phase: player_line(a, "Guerschon Yabusele", 40, ("rebounds",)),
        lambda a, phase: allowed_line(a, "Guerschon Yabusele", 40, ("rebounds",)),
    ),
    FollowUpSession(
        "How did they beat Brooklyn on January 21?",
        44,
        "What was their biggest quarter?",
        lambda a, phase: quarter_case(a, 44),
        lambda a, phase: allowed_quarter(a, 44),
    ),
    FollowUpSession(
        "How did the Houston game go on February 21?",
        57,
        "How many points did Alvarado score?",
        lambda a, phase: player_line(a, "Jose Alvarado", 57, ("points",)),
        lambda a, phase: allowed_line(a, "Jose Alvarado", 57, ("points",)),
    ),
    FollowUpSession(
        "What happened in Memphis on April 1?",
        77,
        "How many did they score in the third?",
        lambda a, phase: quarter_score_case(a, 77, 3),
        lambda a, phase: [
            str(a.quarter(77, 3).nyk_points),
            str(a.quarter(77, 3).opponent_points),
        ],
    ),
]


def follow_up_order_digest(sessions: list[FollowUpSession]) -> str:
    payload = "".join(f"{session.first_question}\x1f{session.follow_up}\n" for session in sessions)
    return hashlib.sha256(payload.encode()).hexdigest()
