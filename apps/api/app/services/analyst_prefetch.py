"""Backend tool choice for clear lookups, so the first provider call carries evidence."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, cast

from app.services.evidence_contracts import ToolCall
from app.services.query_classifier import classify_query

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools

# Questions whose answer depends on live, future or non-archive state are refused by the
# model; prefetching archive evidence would only add a call and could invite an answer.
_SKIP = re.compile(
    r"\b(will|would|tonight|today|tomorrow|live|injur\w*|trade[sd]?|next game|upcoming|"
    r"future|currently|right now|what happened|20[3-9]\d)\b",
    re.I,
)
_TEAM_AGGREGATE = re.compile(
    r"\b(record|wins?|losses?|points?|margin|score|scored|perform|offense|offensive)\b", re.I
)
_TEAM_WINDOW = re.compile(r"\b(this season|season|per game|average|avg|total)\b", re.I)
_AVERAGE = re.compile(r"\b(average|avg|per game)\b", re.I)
_EXPLANATION = re.compile(r"^\s*(?:why|explain)\b|\bexplain\b", re.I)
_BENCH = re.compile(r"\b(bench|lineup)\b", re.I)
_COMPARATIVE = re.compile(r"\b(compare|better|worse|more productive| or )\b", re.I)
_PLAYER_ONLY_METRICS = {
    "turnovers",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "three_pointers_made",
    "minutes",
    "plus_minus",
}
PlayerMetric = Literal[
    "points",
    "rebounds",
    "assists",
    "turnovers",
    "steals",
    "blocks",
    "three_pointers_made",
    "plus_minus",
    "minutes",
]
_PLAYER_METRICS = (
    ("three_pointers_made", re.compile(r"\b(threes?|3s|3-point|three-point)\b", re.I)),
    ("rebounds", re.compile(r"\brebounds?\b", re.I)),
    ("assists", re.compile(r"\bassists?\b", re.I)),
    ("turnovers", re.compile(r"\bturnovers?\b", re.I)),
    ("steals", re.compile(r"\bsteals?\b", re.I)),
    ("blocks", re.compile(r"\bblocks?\b", re.I)),
    ("minutes", re.compile(r"\bminutes\b", re.I)),
    ("plus_minus", re.compile(r"\bplus.minus\b", re.I)),
    ("points", re.compile(r"\b(points?|scor\w*)\b", re.I)),
)


def prefetch_calls(tools: AnalystTools) -> list[ToolCall]:
    """Tools the backend can choose without a model call when the question is clear.

    Base traces spend the first provider round trip choosing exactly one of
    discover_facts (narrative, turning points, player questions) or get_team_stats
    (season/window team aggregates). Clarifications and live/future questions are
    answered directly, so they are left to the model.
    """
    scope = tools.scope
    if scope is None or scope.requires_clarification:
        return []
    question = tools.question
    if scope.team_ids and not scope.player_ids and re.search(r"\bwhat happened\b", question, re.I):
        return [ToolCall(name="get_team_stats", question=question, aggregation="total")]
    if _SKIP.search(question):
        return []
    if len(scope.player_ids) > 1:
        return []
    if len(scope.game_ids) == 1 and not scope.player_ids and _EXPLANATION.search(question):
        # An explanation of one archived game starts from the result, not from a
        # single-game highlight that cannot say what the score was.
        return [ToolCall(name="get_team_stats", question=question, aggregation="total")]
    if tools.topic != question:
        # "And overall?" re-asks the previous topic in a new scope. The topic only picks the
        # tool; the call carries the follow-up itself, so dispatch resolves the new scope
        # and never the topic's own phase or game_ids.
        aggregation: Literal["average", "total"] = (
            "average"
            if tools.aggregation == "average"
            or (tools.aggregation is None and _AVERAGE.search(tools.topic))
            else "total"
        )
        if scope.player_ids:
            # The topic was a player question and the follow-up only moved the window,
            # phase, opponent or site. The inherited metric still names the stat.
            if len(scope.player_ids) == 1 and tools.aggregation in {"average", "total"}:
                metric = scope.metric or next(
                    (name for name, pattern in _PLAYER_METRICS if pattern.search(tools.topic)),
                    None,
                )
                return [
                    ToolCall(
                        name="get_player_stats",
                        question=question,
                        metric=cast("PlayerMetric", metric or "points"),
                        aggregation=aggregation,
                    )
                ]
            return [ToolCall(name="discover_facts", question=question)]
        if not _TEAM_AGGREGATE.search(tools.topic) or _COMPARATIVE.search(tools.topic):
            return []
        return [ToolCall(name="get_team_stats", question=question, aggregation=aggregation)]
    if (
        scope.player_ids
        and scope.opponent_id
        and re.search(r"\b(vs\.?|versus|against)\b", question, re.I)
    ):
        return []
    if scope.player_ids:
        metric = scope.metric
        if metric is None:
            metric = next(
                (name for name, pattern in _PLAYER_METRICS if pattern.search(question)), None
            )
        # A single-player average is a player-stat request even when the question omits a
        # metric word; get_player_stats defaults to points, like the model's first action.
        # discover_facts would return game logs and cannot satisfy an average question.
        # The inherited aggregation keeps "what about Towns?" on the same average.
        player_aggregation: Literal["average", "total"] | None = (
            "average"
            if tools.aggregation == "average" or _AVERAGE.search(question)
            else "total"
            if tools.aggregation == "total"
            else None
        )
        if len(scope.player_ids) == 1 and player_aggregation is not None:
            return [
                ToolCall(
                    name="get_player_stats",
                    question=question,
                    metric=cast("PlayerMetric", metric or "points"),
                    aggregation=player_aggregation,
                )
            ]
        return [ToolCall(name="discover_facts", question=question)]
    if _BENCH.search(question):
        return [ToolCall(name="discover_facts", question=question)]
    if not classify_query(question).is_aggregative:
        return [ToolCall(name="discover_facts", question=question)]
    if scope.metric in _PLAYER_ONLY_METRICS:
        if _COMPARATIVE.search(question):
            return []
        return [ToolCall(name="discover_facts", question=question)]
    windowed = bool(
        _TEAM_WINDOW.search(question)
        or scope.date_start
        or scope.relative_game_count
        or scope.home_away
        or scope.game_result
        or (scope.team_ids and re.search(r"\bvs\.?\b", question, re.I))
    )
    # Home/away and two-opponent comparisons need more than one population.
    if windowed and _TEAM_AGGREGATE.search(question) and not _COMPARATIVE.search(question):
        aggregation = (
            "average" if tools.aggregation == "average" or _AVERAGE.search(question) else "total"
        )
        return [ToolCall(name="get_team_stats", question=question, aggregation=aggregation)]
    return []
