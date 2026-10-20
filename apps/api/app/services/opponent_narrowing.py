"""Apply a question's own condition to candidate games before asking which one it means."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

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
_ERASED_DEFICIT = re.compile(
    r"\b(?:erase|erases|erased|erasing|overcome|overcomes|overcame|overcoming)\b"
    r".{0,24}\bdeficit\b|\bdeficit\b.{0,24}\b(?:erase|erases|erased|erasing|"
    r"overcome|overcomes|overcame|overcoming)\b"
)
_LOST = re.compile(r"\b(?:lose|loses|lost|losing|loss|losses)\b")
_LOST_CONTROL = re.compile(r"\blos(?:e|es|t|ing) control\b")
_WON = re.compile(r"\b(?:win|wins|won|beat|beats|victory|victories)\b")
_CLOSEST = re.compile(r"\bclosest\b|\b(?:smallest|narrowest) (?:final )?margin\b")
_BIGGEST_WIN = re.compile(
    r"\b(?:biggest|best|largest) (?:knicks'? )?(?:win|game)\b|\blargest winning margin\b"
)


LeadCondition = Literal["lost_lead", "comeback", "erased_deficit"]


def lead_change_conditions(question: str) -> tuple[LeadCondition, ...]:
    normalized = question.lower().replace("-", " ")
    conditions: list[LeadCondition] = []
    if _LEAD_LOST.search(normalized):
        conditions.append("lost_lead")
    if _COMEBACK.search(normalized):
        conditions.append("comeback")
    if _ERASED_DEFICIT.search(normalized):
        conditions.append("erased_deficit")
    return tuple(conditions)


def requires_lead_change(question: str) -> bool:
    return bool(lead_change_conditions(question))


@dataclass(frozen=True)
class LeadTransition:
    period: int
    sequence: int
    clock: str
    kind: Literal["knicks_took_lead", "opponent_took_lead", "tied"]
    knicks_score: int
    opponent_score: int


@dataclass(frozen=True)
class Narrowing:
    games: list[Game]
    requirement: str
    unverified_games: list[Game] = field(default_factory=list)


@dataclass(frozen=True)
class LeadFlags:
    lost_lead: bool
    comeback: bool
    erased_deficit: bool
    transitions: tuple[LeadTransition, ...] = ()


async def narrow_by_condition(
    db: AsyncSession,
    question: str,
    games: list[Game],
    *,
    record_request: bool = False,
) -> Narrowing | None:
    """Return the games that satisfy the question's condition, or None if it states none.

    Final-score conditions read the game row. Lead conditions read play-by-play, so a game
    the Knicks won can still be one where they lost a lead. A game with an inconsistent or
    unreconciled scoreboard remains unverified instead of being treated as a match.
    """
    q = question.lower().replace("-", " ")
    requirements: list[str] = []
    selected = list(games)
    unverified_games: list[Game] = []
    lead_lost = bool(_LEAD_LOST.search(q))
    comeback = bool(_COMEBACK.search(q))
    erased_deficit = bool(_ERASED_DEFICIT.search(q))
    outcome_text = _LOST_CONTROL.sub(" ", _LEAD_LOST.sub(" ", q))
    lost, won = bool(_LOST.search(outcome_text)), bool(_WON.search(outcome_text))
    if lost != won and not record_request:
        if won:
            selected = [g for g in selected if g.status == "final" and scores(g)[0] > scores(g)[1]]
            requirements.append("a Knicks win")
        else:
            selected = [g for g in selected if g.status == "final" and scores(g)[0] < scores(g)[1]]
            requirements.append("a Knicks loss")
    if (lead_lost or comeback or erased_deficit) and selected:
        flags = await verified_lead_flags(db, selected)
        unverified_games = [game for game in selected if game.id not in flags]
        selected = [game for game in selected if game.id in flags]
        if lead_lost:
            selected = [game for game in selected if flags[game.id].lost_lead]
            requirements.append("a Knicks lead that the opponent later took")
        if comeback:
            selected = [game for game in selected if flags[game.id].comeback]
            requirements.append("a Knicks deficit that they later turned into a lead")
        if erased_deficit:
            selected = [game for game in selected if flags[game.id].erased_deficit]
            requirements.append("a Knicks deficit that they later tied or overcame")
    if _CLOSEST.search(q):
        final_games = [g for g in selected if g.status == "final"]
        if final_games:
            value = min(abs(scores(g)[0] - scores(g)[1]) for g in final_games)
            selected = [g for g in final_games if abs(scores(g)[0] - scores(g)[1]) == value]
        else:
            selected = []
        requirements.append("the smallest final margin")
    elif _BIGGEST_WIN.search(q):
        wins = [g for g in selected if g.status == "final" and scores(g)[0] > scores(g)[1]]
        value = max((scores(g)[0] - scores(g)[1] for g in wins), default=0)
        selected = [g for g in wins if scores(g)[0] - scores(g)[1] == value]
        requirements.append("the largest Knicks winning margin")
    if not requirements:
        return None
    return Narrowing(selected, " and ".join(dict.fromkeys(requirements)), unverified_games)


async def verified_lead_flags(db: AsyncSession, games: list[Game]) -> dict[int, LeadFlags]:
    """Return lead transitions only for complete, internally consistent scoreboards."""
    rows = (
        await db.execute(
            select(
                GameEvent.game_id,
                GameEvent.period,
                GameEvent.sequence,
                GameEvent.clock,
                GameEvent.home_score,
                GameEvent.away_score,
                GameEvent.score_margin,
                GameEvent.score_observed,
            )
            .where(GameEvent.game_id.in_([g.id for g in games]))
            .order_by(GameEvent.game_id, GameEvent.period, GameEvent.sequence)
        )
    ).all()
    by_game: dict[int, list[Any]] = {}
    for row in rows:
        by_game.setdefault(row.game_id, []).append(row)
    flags: dict[int, LeadFlags] = {}
    for game in games:
        if game.status != "final":
            continue
        events = by_game.get(game.id, [])
        if not events:
            continue
        nyk_home = game.home_team_id == "NYK"
        previous = (0, 0)
        led = trailed = lost_lead = came_back = erased_deficit = False
        has_observed_scores = False
        valid_scoreboard = True
        sequences: set[int] = set()
        transitions: list[LeadTransition] = []
        for row in events:
            if row.sequence in sequences:
                valid_scoreboard = False
            sequences.add(row.sequence)
            previous_margin = previous[0] - previous[1] if nyk_home else previous[1] - previous[0]
            current = cumulative_score(row, previous)
            score_is_observed = row.score_observed is True or (
                row.score_observed is None and (row.home_score, row.away_score) != (0, 0)
            )
            if score_is_observed:
                has_observed_scores = True
                if row.score_margin != row.home_score - row.away_score:
                    valid_scoreboard = False
            home_points = current[0] - previous[0]
            away_points = current[1] - previous[1]
            if home_points < 0 or away_points < 0 or (home_points > 0 and away_points > 0):
                valid_scoreboard = False
            previous = current
            margin = previous[0] - previous[1] if nyk_home else previous[1] - previous[0]
            previous_sign = (previous_margin > 0) - (previous_margin < 0)
            current_sign = (margin > 0) - (margin < 0)
            if previous_sign != current_sign:
                kind = (
                    "knicks_took_lead"
                    if margin > 0
                    else "opponent_took_lead"
                    if margin < 0
                    else "tied"
                )
                knicks_score, opponent_score = current if nyk_home else (current[1], current[0])
                transitions.append(
                    LeadTransition(
                        period=row.period,
                        sequence=row.sequence,
                        clock=row.clock,
                        kind=kind,
                        knicks_score=knicks_score,
                        opponent_score=opponent_score,
                    )
                )
            if margin > 0:
                came_back = came_back or trailed
                erased_deficit = erased_deficit or trailed
                led = True
            elif margin < 0:
                lost_lead = lost_lead or led
                trailed = True
            else:
                erased_deficit = erased_deficit or trailed
        if (
            valid_scoreboard
            and has_observed_scores
            and previous
            == (
                game.home_score,
                game.away_score,
            )
        ):
            flags[game.id] = LeadFlags(
                lost_lead,
                came_back,
                erased_deficit,
                tuple(transitions),
            )
    return flags
