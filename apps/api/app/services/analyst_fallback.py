"""Facts that may answer a turn whose model answer failed validation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.evidence_contracts import ToolResult, VerifiedClaim
from app.services.query_resolution import is_record_request

if TYPE_CHECKING:
    from app.services.analyst_loop import AnalystLoop


def re_search_discovery(question: str) -> bool:
    return bool(
        re.search(
            r"\b(interesting|surprising|notable|fun|another|different player)\b", question, re.I
        )
    )


def fallback_claims(loop: AnalystLoop) -> list[VerifiedClaim]:
    """Only release/scope-matched facts can answer a failed turn.

    Prior claims may be valid historical facts without answering this question.
    Reuse current tool work only when its complete population and metric match.
    """
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
    games = tools.selected_games(scope)
    if is_record_request(tools.question) and not scope.player_ids:
        games = [g for g in games if g.status == "final" and g.home_score != g.away_score]
    if scope.relative_game_count:
        games = games[-scope.relative_game_count :]
    expected_games = {g.id for g in games}
    discovery = re_search_discovery(tools.question)
    claims = []
    results = list(loop.results)
    if is_record_request(tools.question) and not scope.player_ids:
        # Revalidated prior record totals are reusable only for the exact population.
        results.append(ToolResult(status="ok", message="", claims=list(tools.claims.values())))
    for result in results:
        for claim in result.claims:
            if claim.release_id != tools.release.version:
                continue
            if not claim.supporting_evidence_ids or any(
                ref not in tools.evidence or tools.evidence[ref].release_id != tools.release.version
                for ref in claim.supporting_evidence_ids
            ):
                continue
            if discovery:
                relevant = bool(result.candidates) and set(claim.game_ids or []) <= expected_games
            else:
                subject = (
                    claim.subject_id in {f"player:{pid}" for pid in scope.player_ids}
                    if scope.player_ids
                    else claim.subject_id == "team:NYK"
                )
                population = expected_games
                if scope.player_ids:
                    population = {
                        stat.game_id
                        for stat, _ in tools.rows
                        if f"player:{stat.player_id}" == claim.subject_id
                        and stat.minutes > 0
                        and stat.game_id in expected_games
                    }
                relevant = subject and set(claim.game_ids or []) == population
                if scope.player_ids:
                    relevant = relevant and claim.metric_id.split(":")[0] == (
                        scope.metric or "points"
                    )
            if relevant:
                claims.append(claim)
    if is_record_request(tools.question) and not scope.player_ids:
        claims = [c for c in claims if c.metric_id in {"wins", "losses"}]
        if {c.metric_id for c in claims} != {"wins", "losses"}:
            return []
    return list({c.claim_id: c for c in claims}.values())
