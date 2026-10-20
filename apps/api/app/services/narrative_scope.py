"""Require a verifiable game and measure before describing a narrative sequence."""

from __future__ import annotations

import re

from app.models.game import Game
from app.services.canonical_narrative import measure_clarification
from app.services.opponent_narrowing import narrow_by_condition, requires_lead_change
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
_OUTCOME_CONDITION = re.compile(
    r"\b(?:win|wins|won|lose|loses|lost|loss|losses|closest|biggest win)\b"
)
_SCORING_SEQUENCE = re.compile(
    r"\b(?:biggest run|scoring run|most damaging|largest deficit|collapse|collpase|"
    r"drought|decisive|key sequence|turning point|game turn|lose control|broke open|comeback)\b"
)
_RUN_DEFINITION = (
    "Should I measure unanswered points, net scoring margin, or a particular time window? "
    "Those describe the sequence without assuming it caused the result."
)


def _reference_clarification(question: str) -> str:
    answer = "Which game/date and which event, stretch, or claim are you referring to?"
    if re.search(r"\b(?:worst|best)\b", question, re.I):
        answer += " Which comparison measure and game/time scope should I use?"
    if re.search(r"\b(?:compare|the other)\b", question, re.I):
        answer += " Which game/date should I compare it with?"
    return answer


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
    clarification = measure_clarification(question)
    if clarification and not references_only:
        return clarification
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
        or requires_lead_change(question)
        or (not classify_query(question).is_aggregative and _OUTCOME_CONDITION.search(q))
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
    if "best defensive game" in normalized and candidates:
        minimum = min(scores(game)[1] for game in candidates)
        candidates = [game for game in candidates if scores(game)[1] == minimum]
    opponents = team_ids_in_text(context) - {"NYK"}
    narrowing = await narrow_by_condition(db, normalized, candidates) if candidates else None
    if narrowing and narrowing.unverified_games:
        verified_dates = ", ".join(dict.fromkeys(str(game.game_date) for game in narrowing.games))
        unverified_dates = ", ".join(
            dict.fromkeys(str(game.game_date) for game in narrowing.unverified_games)
        )
        verified = f"Verified matching game dates: {verified_dates}. " if verified_dates else ""
        return (
            f"{verified}I cannot verify {unverified_dates} because their play-by-play "
            "scoreboards are missing, malformed, or do not reconcile with the final score. "
            "Which archived game date should I use?"
        )
    if narrowing and not narrowing.games:
        against = f" against {'/'.join(sorted(opponents))}" if opponents else ""
        return (
            f"No archived Knicks game{against} matches that. None of the {len(candidates)} "
            f"archived games{against} shows {narrowing.requirement}."
        )
    if narrowing:
        candidates = narrowing.games
    if (
        selected_game_ids
        and len(candidates) > 1
        and re.search(r"\b(?:closest|biggest win|best win)\b", normalized)
    ):
        return None
    if len(candidates) != 1:
        if reference:
            return _reference_clarification(question)
        opponents = team_ids_in_text(context) - {"NYK"}
        opponent = f" {'/'.join(sorted(opponents))}" if opponents else ""
        if opponents and candidates:
            dates = ", ".join(dict.fromkeys(str(game.game_date) for game in candidates))
            selection = f"Which archived{opponent} game date should I use: {dates}?"
        else:
            selection = f"Which archived{opponent} game date or opponent should I use?"
        if _SCORING_SEQUENCE.search(q):
            selection += " " + _RUN_DEFINITION
        return selection
    if _SCORING_SEQUENCE.search(q):
        return f"For {candidates[0].game_date}, {_RUN_DEFINITION}"
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
