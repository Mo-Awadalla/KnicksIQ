"""Facts that may answer a turn whose model answer failed validation.

A fallback must answer the question asked or say plainly that it cannot. Reusing a true
aggregate from an unrelated tool call presents the wrong answer with confident receipts.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.evidence_contracts import ToolResult, VerifiedClaim
from app.services.query_resolution import is_record_request

if TYPE_CHECKING:
    from app.services.analyst_loop import AnalystLoop

_EXTREME = re.compile(
    r"\b(?:worst|best|biggest|largest|highest|lowest|fewest|least|heaviest|top)\b"
    r"|\bcollapse\b|\bcomeback\b|\bdeficit\b|\bblown\b",
    re.I,
)
_RECORD = re.compile(r"\bhow many\b[^?.]*\b(?:wins?|losses?|games?)\b", re.I)


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


def _family(tools) -> str:
    """What kind of answer this question needs, or "" when the archive cannot answer it."""
    question = tools.question
    scope = tools.scope
    if re_search_live(question):
        return "live"
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
    if scope.opponent_id:
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
    if (
        scope is None
        or scope.requires_clarification
        or scope.periods
        or tools.season != tools.release.season
        or any(
            season != tools.release.season
            for season in re.findall(r"\b20\d{2}-\d{2}(?!-\d{2})\b", tools.question)
        )
    ):
        return []
    family = _family(tools)
    if not family or family == "live":
        # No archived fact answers a live/current-date question.
        return []
    games = tools.selected_games(scope)
    if family in {"record", "matchup", "extreme"}:
        games = [g for g in games if g.status == "final" and g.home_score != g.away_score]
    if scope.relative_game_count:
        games = games[-scope.relative_game_count :]
    expected_games = {g.id for g in games}
    wanted = _metric_family(tools.question)
    results = list(loop.results)
    if family in {"record", "matchup"} and not scope.player_ids:
        # Revalidated prior record totals are reusable only for the exact population.
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


def decline_text(loop: AnalystLoop) -> str:
    """A plain coverage statement; never unrelated aggregates dressed as an answer."""
    tools = loop.tools
    latest = tools.games[-1].game_date if tools.games else None
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
