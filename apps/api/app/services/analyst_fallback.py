"""Facts that may answer a turn whose model answer failed validation.

A fallback must answer the question asked or say plainly that it cannot. Reusing a true
aggregate from an unrelated tool call presents the wrong answer with confident receipts.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.analyst_prefetch import flow_requested, period_requested, split_requested
from app.services.analyst_tool_registry import recovery_tool
from app.services.evidence_contracts import ToolCall, ToolResult, VerifiedClaim
from app.services.query_text import is_record_request

if TYPE_CHECKING:
    from app.services.analyst_loop import AnalystLoop

_EXTREME = re.compile(
    r"\b(?:worst|best|biggest|largest|highest|lowest|fewest|least|heaviest|top)\b"
    r"|\bcollapse\b|\bcomeback\b|\bdeficit\b|\bblown\b",
    re.I,
)
_RECORD = re.compile(r"\bhow many\s+(?:total\s+)?(?:wins?|losses?|games?)\b", re.I)
# A forecast is not an archive fact. "Will you/I ..." is a request to show archive data,
# not a prediction, so only future scopes and predictive phrasing make the turn
# unanswerable; the addressee forms keep their archive answer.
_FUTURE = re.compile(
    r"\b(?:next|upcoming|future|following)\s+"
    r"(?:season|year|game|games|playoffs?|postseason|month|week)\b"
    r"|\btomorrow\b|\bpredict\w*\b|\bprojections?\b|\bforecast\w*\b|\bgoing forward\b"
    r"|\b(?:will|won't|would)\s+(?!(?:you|i)\b)"
    r"(?:\w+\s+){0,4}?(?:play|score|do|be|have|win|make|average|perform|lead|start|"
    r"return|improve|regress|contend|reach)\b",
    re.I,
)
_FLOW_CLAIM_METRICS = frozenset(
    {
        "biggest_run",
        "biggest_run_in_loss",
        "largest_deficit_erased",
        "largest_comeback_run",
        "largest_deficit_in_loss",
        "largest_lead_lost",
        "final_score",
        "largest_lead",
        "lead_changes",
        "ties",
        "decisive_run",
        "deficit_erased",
        "comeback_scoring",
        "comeback_run",
        "lead_lost",
    }
)


def re_search_discovery(question: str) -> bool:
    return bool(
        re.search(
            r"\b(interesting|surprising|notable|fun|another|different player)\b", question, re.I
        )
    )


def re_search_live(question: str) -> bool:
    return bool(
        re.search(r"\b(injur\w*|today|yesterday|current|live|tonight|nowadays)\b", question, re.I)
    )


def future_requested(question: str) -> bool:
    """A prediction or a future-time scope the archive cannot answer."""
    return bool(_FUTURE.search(question))


def _family(tools) -> str:
    """What kind of answer this question needs, or "" when the archive cannot answer it."""
    # "And in the playoffs?" asks the previous topic in a new scope; the scope is already
    # resolved, so the topic decides what kind of fact answers it.
    question = tools.topic
    scope = tools.scope
    if re_search_live(tools.question) or re_search_live(question):
        return "live"
    if future_requested(tools.question) or future_requested(question):
        return "future"
    # The same question shape that chose a specialized tool in prefetch chooses its
    # claim family here. Without this, a reviewer rejection discards valid split, flow
    # or period claims and delivers a decline for an answerable question.
    for text in (tools.question, question):
        if flow_requested(text):
            return "flow"
        if split_requested(text, scope):
            return "splits"
        if period_requested(text, scope):
            return "periods"
    if (
        len(scope.game_ids or []) == 1
        and not scope.player_ids
        and re.search(r"^\s*(?:why|explain)\b|\bexplain\b", question, re.I)
    ):
        # An explanation of one archived game is answered by that game's result.
        return "game"
    if re_search_discovery(question):
        return "discovery"
    if _EXTREME.search(question):
        return "extreme"
    if scope.player_ids:
        return "player"
    if (
        is_record_request(question)
        or _RECORD.search(question)
        or re.search(r"\brecord\b", question, re.I)
    ):
        return "record"
    if scope.opponent_id and not re.search(
        r"\b(?:points?|scor(?:e|ed|ing)|margin|total|average|avg|per game)\b", question, re.I
    ):
        # A matchup asks wins and losses only when no countable stat was named.
        return "matchup"
    if re.search(r"\bmargin\b", question, re.I):
        return "margin"
    if re.search(r"\b(?:points?|scor(?:e|ed|ing)|total)\b", question, re.I):
        return "points"
    return ""


def _metric_family(question: str) -> set[str]:
    wanted = set()
    if re.search(r"\bwins?\b|\bwon\b|\brecord\b", question, re.I):
        wanted.update({"wins", "losses"})
    if re.search(r"\bmargin\b", question, re.I):
        wanted.update({"margin", "margin_per_game"})
    if re.search(r"\b(?:points?|scor(?:e|ed|ing)|total)\b", question, re.I):
        wanted.update({"points", "points_per_game"})
    return wanted


def fallback_claims(loop: AnalystLoop) -> list[VerifiedClaim]:
    """Only release/scope-matched facts that answer this question can answer a failed turn."""
    tools = loop.tools
    scope = tools.scope
    if scope is None:
        return []
    family = _family(tools)
    # A period-scoped question is answerable by the period tool; every other tool reports
    # that scope as unsupported, so its claims cannot answer a failed turn.
    if (
        scope.requires_clarification
        or (scope.periods and family != "periods")
        or tools.season != tools.release.season
        or any(
            season != tools.release.season
            for season in re.findall(r"\b20\d{2}-\d{2}(?!-\d{2})\b", tools.question)
        )
    ):
        return []
    if not family or family in {"live", "future"}:
        # No archived fact answers a live/current-date or future question.
        return []
    games = tools.selected_games(scope)
    if family in {"record", "matchup", "extreme", "game"}:
        games = [g for g in games if g.status == "final" and g.home_score != g.away_score]
    games = scope.window(games)
    expected_games = {g.id for g in games}
    wanted = _metric_family(tools.topic)
    results = list(loop.results)
    if family in {"record", "matchup", "game"} and not scope.player_ids:
        # Revalidated prior totals are reusable only for the exact population.
        results.append(ToolResult(status="ok", message="", claims=list(tools.claims.values())))
    claims: list[VerifiedClaim] = []
    for result in results:
        for claim in result.claims:
            if claim.release_id != tools.release.version:
                continue
            if not claim.supporting_evidence_ids or any(
                ref not in tools.evidence or tools.evidence[ref].release_id != tools.release.version
                for ref in claim.supporting_evidence_ids
            ):
                continue
            claim_games = set(claim.game_ids or [])
            if family == "discovery":
                relevant = bool(result.candidates) and claim_games <= expected_games
            elif family == "record":
                relevant = (
                    claim.subject_id == "team:NYK"
                    and claim_games == expected_games
                    and claim.metric_id in {"wins", "losses"}
                )
            elif family == "matchup":
                # Overall record plus the regular-season/playoff breakdown.
                relevant = (
                    claim.subject_id == "team:NYK"
                    and claim.metric_id in {"wins", "losses"}
                    and (
                        claim_games == expected_games
                        or (claim.season_type is not None and claim_games <= expected_games)
                    )
                )
            elif family == "extreme":
                subject_ok = not scope.player_ids or claim.subject_id in {
                    f"player:{pid}" for pid in scope.player_ids
                }
                relevant = (
                    subject_ok
                    and claim.metric_id.endswith(":extreme")
                    and claim_games <= expected_games
                )
            elif family == "flow":
                relevant = claim.metric_id in _FLOW_CLAIM_METRICS and claim_games <= expected_games
            elif family == "splits":
                # get_team_splits deliberately widens a split question past the resolved
                # scope (home plus road, both opponents), so its buckets are not required
                # to be subsets of the scope's games.
                relevant = claim.metric_id.startswith("team_splits:")
            elif family == "periods":
                relevant = claim.metric_id == "period_report"
            elif family == "game":
                relevant = (
                    claim.subject_id == "team:NYK"
                    and claim.metric_id in {"points", "margin"}
                    and claim_games == expected_games
                )
            elif family == "player":
                subject = {f"player:{pid}" for pid in scope.player_ids}
                population = {
                    stat.game_id
                    for stat, _ in tools.rows
                    if f"player:{stat.player_id}" in subject
                    and stat.minutes > 0
                    and stat.game_id in expected_games
                }
                metric = claim.metric_id.split(":")[0]
                relevant = (
                    claim.subject_id in subject
                    and claim_games == population
                    and metric == (scope.metric or "points")
                )
            else:
                metric = claim.metric_id
                relevant = (
                    claim.subject_id == "team:NYK"
                    and claim_games == expected_games
                    and (
                        metric in wanted
                        or (family == "points" and metric in {"points", "points_per_game"})
                        or (family == "margin" and metric in {"margin", "margin_per_game"})
                    )
                )
            if relevant:
                claims.append(claim)
    if family == "record" or family == "matchup":
        claims = [c for c in claims if c.metric_id in {"wins", "losses"}]
        if {c.metric_id for c in claims} != {"wins", "losses"}:
            return []
    return list({c.claim_id: c for c in claims}.values())


def recovery_call(tools) -> ToolCall:
    """The one tool a failed turn runs: the same question shape that picks a tool up front."""
    scope = tools.scope
    if period_requested(tools.question, scope):
        return ToolCall(name="get_period_scoring", question=tools.question)
    if flow_requested(tools.question):
        return ToolCall(name="get_game_flow", question=tools.question)
    if split_requested(tools.question, scope):
        return ToolCall(name="get_team_splits", question=tools.question)
    spec = recovery_tool(
        "discovery"
        if re_search_discovery(tools.question)
        else "player"
        if scope and scope.player_ids
        else "team"
    )
    return ToolCall(
        name=spec.name,
        question=tools.question,
        aggregation=spec.recovery_aggregation,
    )


def fallback_text(claim: VerifiedClaim) -> str:
    """The sentence a fallback states; a period report carries its text in the value."""
    if claim.metric_id == "period_report":
        return str(claim.value)
    return claim.statement


def decline_text(loop: AnalystLoop) -> str:
    """A plain coverage statement; never unrelated aggregates dressed as an answer."""
    tools = loop.tools
    latest = tools.games[-1].game_date if tools.games else None
    if future_requested(tools.question) or future_requested(tools.topic):
        text = "I can't answer questions about future games or seasons."
        if latest:
            text += f" The archive's most recent game is {latest}."
        return text
    if re_search_live(tools.question):
        text = "I don't have live or current-date data."
        if latest:
            text += f" The archive's most recent game is {latest}."
        return text
    for result in reversed(loop.results):
        if (
            result.status
            in {
                "no_matching_results",
                "unsupported_metric_or_scope",
                "ambiguous_entity",
                "dependency_failure",
            }
            and result.message
        ):
            return result.message + (" " + "; ".join(result.choices) if result.choices else "")
    return "I can't answer that: verified archive facts are unavailable on this turn."
