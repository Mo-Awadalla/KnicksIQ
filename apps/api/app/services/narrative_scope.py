"""Require a verifiable game and measure before describing a narrative sequence."""

from __future__ import annotations

import re

from app.models.game import Game
from app.services.query_classifier import classify_query
from app.services.releases import restrict_to_active_release
from app.services.team_aliases import team_ids_in_text
from app.services.team_scope import scope_games, scores
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_REFERENCE = re.compile(r"\b(?:that|then|next|during it|after that|the other|final possession)\b")
_NARRATIVE = re.compile(
    r"\b(?:what happened|walk me|tell the story|what decided|what changed|why did|"
    r"decisive|key sequence|turning point|collapse|collpase|drought|comeback|"
    r"lose control|scoring run|biggest run|most damaging|largest deficit|"
    r"close the|influence|shape|affect|which plays|late run|after halftime|"
    r"lose the lead|took the lead|game turn|broke open|"
    r"final two minutes|final 2 minutes|describe|explain|which .+ game do you mean)\b"
)


async def narrative_clarification(
    db: AsyncSession,
    question: str,
    *,
    season: str,
    prior_questions: list[str],
    references_only: bool = False,
    selected_game_ids: list[int] | None = None,
) -> str | None:
    q = question.lower()
    if re.search(r"\b(?:python|coding|leetcode|compiler|yankees|mets)\b", q):
        return None
    if (
        "what happened" in q
        and "season" in q
        and not any(term in q for term in ("run", "collapse", "deficit", "game"))
    ):
        return None
    reference = bool(_REFERENCE.search(q))
    if references_only and not reference:
        return None
    if not references_only and not (
        reference
        or _NARRATIVE.search(q)
        or ("the knicks game" in q and not classify_query(question).is_aggregative)
        or re.fullmatch(r"(?:what was the score|who was better|was that a good game)\??", q)
    ):
        return None
    if "why" in q and any(term in q for term in ("pick", "biggest win", "best win")):
        return None
    context = " ".join([*prior_questions, question]) if reference else question
    normalized = context.lower().replace("-", " ")
    if (
        re.search(r"\b(?:biggest|largest|worst|most damaging)\b", q)
        and re.search(r"\b(?:run|deficit|collapse|collpase)\b", q)
        and not (team_ids_in_text(context) - {"NYK"})
        and not re.search(r"\b20\d{2}-\d{2}-\d{2}\b", context)
        and not selected_game_ids
    ):
        return (
            "For this season-wide ranking, should I compare unanswered points, net scoring change, "
            "or deficits erased? What time window should define one run or collapse?"
        )
    if "who was better" in q and not prior_questions:
        return "Which players or teams should I compare, and by which statistic?"
    if re.search(r"\bworst\b.*\bquarter\b", q):
        return "Should worst quarter mean the fewest Knicks points or the worst scoring margin?"
    if "defense" in q and not any(term in q for term in ("game", "best", "points", "allow")):
        return (
            "Which game or date window should I use, "
            "and should I measure points allowed or shooting?"
        )
    stmt = restrict_to_active_release(
        select(Game).where(
            Game.season == season,
            (Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"),
        )
    )
    games = list((await db.execute(stmt.order_by(Game.game_date, Game.id))).scalars())
    candidates = scope_games(context, games)
    if selected_game_ids:
        candidates = [game for game in candidates if game.id in selected_game_ids]
    if "closest" in normalized and candidates:
        minimum = min(abs(scores(game)[0] - scores(game)[1]) for game in candidates)
        candidates = [
            game for game in candidates if abs(scores(game)[0] - scores(game)[1]) == minimum
        ]
    elif (
        any(term in normalized for term in ("biggest win", "best win", "biggest game"))
        and candidates
    ):
        maximum = max(scores(game)[0] - scores(game)[1] for game in candidates)
        candidates = [game for game in candidates if scores(game)[0] - scores(game)[1] == maximum]
    elif "best defensive game" in normalized and candidates:
        minimum = min(scores(game)[1] for game in candidates)
        candidates = [game for game in candidates if scores(game)[1] == minimum]
    if re.search(r"\b(?:the|a|boston|toronto|atlanta|chicago|charlotte) loss\b", normalized):
        candidates = [game for game in candidates if scores(game)[0] < scores(game)[1]]
    if len(candidates) != 1:
        if not candidates:
            return "Which archived game date or opponent should I use? I found no matching game."
        choices = "; ".join(
            f"{game.game_date} vs "
            f"{game.away_team_id if game.home_team_id == 'NYK' else game.home_team_id}"
            for game in candidates[:8]
        )
        return (
            f"Which game do you mean? I found {len(candidates)} matching games: {choices}. "
            "Please choose a date before I describe the sequence."
        )
    if re.search(
        r"\b(?:biggest run|scoring run|most damaging|largest deficit|collapse|collpase|"
        r"drought|decisive|key sequence|turning point|lose control|broke open|comeback)\b",
        q,
    ):
        return (
            f"For {candidates[0].game_date}, should I measure unanswered points, "
            "net scoring margin, or a particular time window? "
            "Those describe the sequence without assuming it caused the result."
        )
    if reference and re.search(
        r"\b(?:stretch|run|then|during it|next|final possession|after that)\b", q
    ):
        explicit_event = bool(
            re.search(
                r"\b(?:q[1-4]|[1-4](?:st|nd|rd|th)? quarter|\d{1,2}:\d{2})\b", context.lower()
            )
        )
        if not explicit_event:
            return (
                f"Which quarter and clock time in the {candidates[0].game_date} game should I use?"
            )
    # Concrete aggregate follow-ups remain on their existing metric route.
    if classify_query(question).is_aggregative and not _NARRATIVE.search(q):
        return None
    return None
