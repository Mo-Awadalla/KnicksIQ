"""Apply a question's own condition to candidate games before asking which one it means."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.event_scores import cumulative_score
from app.services.team_scope import scores
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_LEAD_LOST = re.compile(
    r"\b(?:lose|loses|lost|losing|blew|blow|blows|blown|blowing)\s+"
    r"(?:(?:the|a|an|their|its|that)\s+)?(?:\w+\s+){0,2}?leads?\b"
    r"|\bcollapse[ds]?\b|\bcollpase\b"
)
_COMEBACK = re.compile(r"\bcome ?backs?\b|\bcame back\b")
_LOST = re.compile(r"\b(?:lose|loses|lost|losing|loss|losses)\b")
_LOST_CONTROL = re.compile(r"\blos(?:e|es|t|ing) control\b")
_WON = re.compile(r"\b(?:win|wins|won|beat|beats|victory|victories)\b")
_CLOSEST = re.compile(r"\bclosest\b|\b(?:smallest|narrowest) (?:final )?margin\b")
_BIGGEST_WIN = re.compile(
    r"\b(?:biggest|best|largest) (?:knicks'? )?(?:win|game)\b|\blargest winning margin\b"
)


def requires_lead_change(question: str) -> bool:
    normalized = question.lower().replace("-", " ")
    return bool(_LEAD_LOST.search(normalized) or _COMEBACK.search(normalized))


@dataclass(frozen=True)
class Narrowing:
    games: list[Game]
    requirement: str


async def narrow_by_condition(
    db: AsyncSession,
    question: str,
    games: list[Game],
    *,
    record_request: bool = False,
) -> Narrowing | None:
    """Return the games that satisfy the question's condition, or None if it states none.

    Final-score conditions read the game row. Lead conditions read play-by-play, so a game
    the Knicks won can still be one where they lost a lead. A game whose play-by-play does
    not reconcile with its final score cannot be excluded and stays a candidate.
    """
    q = question.lower().replace("-", " ")
    requirements: list[str] = []
    selected = list(games)
    lead_lost, comeback = bool(_LEAD_LOST.search(q)), bool(_COMEBACK.search(q))
    outcome_text = _LOST_CONTROL.sub(" ", _LEAD_LOST.sub(" ", q))
    lost, won = bool(_LOST.search(outcome_text)), bool(_WON.search(outcome_text))
    if lost != won and not record_request:
        selected = [g for g in selected if (scores(g)[0] > scores(g)[1]) == won]
        requirements.append("a Knicks win" if won else "a Knicks loss")
    if (lead_lost or comeback) and selected:
        flags = await _lead_flags(db, selected)
        if lead_lost:
            selected = [g for g in selected if flags.get(g.id, (True, True))[0]]
            requirements.append("a Knicks lead that the opponent later tied or overtook")
        if comeback:
            selected = [g for g in selected if flags.get(g.id, (True, True))[1]]
            requirements.append("a Knicks deficit that they later turned into a lead")
    elif lead_lost or comeback:
        requirements.append("a lead change")
    if _CLOSEST.search(q) and selected:
        value = min(abs(scores(g)[0] - scores(g)[1]) for g in selected)
        selected = [g for g in selected if abs(scores(g)[0] - scores(g)[1]) == value]
        requirements.append("the smallest final margin")
    elif _BIGGEST_WIN.search(q):
        wins = [g for g in selected if scores(g)[0] > scores(g)[1]]
        value = max((scores(g)[0] - scores(g)[1] for g in wins), default=0)
        selected = [g for g in wins if scores(g)[0] - scores(g)[1] == value]
        requirements.append("the largest Knicks winning margin")
    if not requirements:
        return None
    return Narrowing(selected, " and ".join(dict.fromkeys(requirements)))


async def _lead_flags(db: AsyncSession, games: list[Game]) -> dict[int, tuple[bool, bool]]:
    """Map game id to (Knicks lead later tied or lost, Knicks deficit later turned into a lead)."""
    rows = (
        await db.execute(
            select(
                GameEvent.game_id,
                GameEvent.home_score,
                GameEvent.away_score,
                GameEvent.score_observed,
            )
            .where(GameEvent.game_id.in_([g.id for g in games]))
            .order_by(GameEvent.game_id, GameEvent.period, GameEvent.sequence)
        )
    ).all()
    by_game: dict[int, list[Any]] = {}
    for row in rows:
        by_game.setdefault(row.game_id, []).append(row)
    flags: dict[int, tuple[bool, bool]] = {}
    for game in games:
        nyk_home = game.home_team_id == "NYK"
        previous = (0, 0)
        led = trailed = lost_lead = came_back = False
        for row in by_game.get(game.id, []):
            previous = cumulative_score(row, previous)
            margin = previous[0] - previous[1] if nyk_home else previous[1] - previous[0]
            if margin > 0:
                came_back = came_back or trailed
                led = True
            else:
                lost_lead = lost_lead or led
                trailed = trailed or margin < 0
        if previous == (game.home_score, game.away_score) and game.id in by_game:
            flags[game.id] = (lost_lead, came_back)
    return flags
