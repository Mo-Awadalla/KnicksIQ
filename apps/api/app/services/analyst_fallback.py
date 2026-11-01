"""Facts that may answer a turn whose model answer failed validation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.analyst_comparisons import player_claim_metrics, player_comparison_rows
from app.services.analyst_player_stats import metric_id_for
from app.services.evidence_contracts import ToolResult, VerifiedClaim
from app.services.query_comparison_specs import team_claim_metrics
from app.services.query_operations import (
    GAME_SCORE_METRIC,
    GAME_SUMMARY_METRICS,
    is_record_request,
)

if TYPE_CHECKING:
    from app.services.analyst_loop import AnalystLoop
    from app.services.analyst_tools import AnalystTools
    from app.services.query_resolution import ResolvedQuery


def re_search_discovery(question: str) -> bool:
    return bool(
        re.search(
            r"\b(interesting|surprising|notable|fun|another|different player)\b", question, re.I
        )
    )


def _operation(loop: AnalystLoop) -> str:
    """The population key a team claim must carry to answer this question."""
    scope = loop.tools.scope
    assert scope is not None
    if scope.comparison is not None:
        return "team_comparison"
    return scope.operation or "team_aggregate"


def _operations(loop: AnalystLoop) -> frozenset[str]:
    """Every operation the authoritative request asks for.

    A compound request names more than one supported measure, so each of its claims is
    relevant; reducing to the first operation would silently drop the others.
    """
    scope = loop.tools.scope
    assert scope is not None
    measures = getattr(scope, "requested_measures", ())
    if measures:
        return frozenset(measure.operation for measure in measures)
    return frozenset({_operation(loop)})


def _comparison_claim_relevant(
    claim: VerifiedClaim, scope: ResolvedQuery, tools: AnalystTools
) -> bool:
    """A comparison claim answers only its own group, metric and complete group games."""
    spec = getattr(scope, "comparison", None)
    if spec is None:
        return False
    allowed = (
        set(player_claim_metrics(spec))
        if spec.measure == "player_metric"
        else set(team_claim_metrics(spec))
    )
    if claim.metric_id not in allowed:
        return False
    group_key = (claim.eligibility or {}).get("comparison_group")
    if not isinstance(group_key, str):
        return False
    group = next((item for item in spec.groups if item.key == group_key), None)
    if group is None:
        return False
    population = tools.comparison_populations(scope)[group_key]
    if spec.measure == "player_metric":
        player_id = next(
            (pid for pid in scope.player_ids if claim.subject_id == f"player:{pid}"), None
        )
        if player_id is None:
            return False
        rows, _ = player_comparison_rows(tools, scope, group, player_id)
        expected = {row.game_id for row, _ in rows}
    else:
        if claim.subject_id != "team:NYK":
            return False
        expected = {game.id for game in population}
    return bool(expected) and set(claim.game_ids or []) == expected


def fallback_claims(loop: AnalystLoop) -> list[VerifiedClaim]:
    """Only release/scope/operation-matched facts can answer a failed turn.

    Prior claims may be valid historical facts without answering this question.
    Reuse current tool work only when its complete population and metric match.
    """
    tools = loop.tools
    scope = tools.scope
    if (
        scope is None
        or scope.requires_clarification
        or scope.operation_reason
        or (scope.periods and scope.operation != "period_scoring")
        or tools.season != tools.release.season
        or any(
            season != tools.release.season
            for season in re.findall(r"\b20\d{2}-\d{2}(?!-\d{2})\b", tools.question)
        )
    ):
        return []
    operations = _operations(loop)
    expected_games = {g.id for g in tools.considered_games(scope)}
    expected_considered = None if scope.operation == "game_swings" else expected_games
    discovery = re_search_discovery(tools.question)
    claims = []
    results = list(loop.results)
    if is_record_request(tools.question) and not scope.player_ids and scope.comparison is None:
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
            elif scope.operation == "player_leaderboard":
                relevant = _leaderboard_claim_relevant(claim, scope, expected_games)
            elif scope.comparison is not None:
                relevant = _comparison_claim_relevant(claim, scope, tools)
            elif scope.operation == "player_game_summary":
                relevant = _game_summary_claim_relevant(claim, scope, expected_games)
            elif scope.player_ids:
                expected_metric = metric_id_for(scope.stat) if scope.stat else None
                subject = claim.subject_id in {f"player:{pid}" for pid in scope.player_ids}
                population = {
                    stat.game_id
                    for stat, _ in tools.rows
                    if f"player:{stat.player_id}" == claim.subject_id
                    and stat.minutes > 0
                    and stat.game_id in expected_games
                }
                relevant = (
                    subject
                    and set(claim.game_ids or []) == population
                    and (
                        claim.metric_id == expected_metric
                        if expected_metric
                        else claim.metric_id.split(":")[0] == (scope.metric or "points")
                    )
                )
            else:
                relevant = _team_claim_relevant(
                    claim,
                    operations=operations,
                    expected_games=expected_games,
                    expected_considered=expected_considered,
                )
            if relevant:
                claims.append(claim)
    if is_record_request(tools.question) and not scope.player_ids and scope.comparison is None:
        claims = [c for c in claims if c.metric_id in {"wins", "losses"}]
        if {c.metric_id for c in claims} != {"wins", "losses"}:
            return []
    return list({c.claim_id: c for c in claims}.values())


def _game_summary_claim_relevant(
    claim: VerifiedClaim, scope: ResolvedQuery, expected_games: set[int]
) -> bool:
    """A one-game summary answers only its own game, subject and reported measures.

    The requested summary measures are the basic statline plus the game's final score, so a
    season average, a threshold count or a different game's line never answers this turn
    even when its release and scope still match.
    """
    if (claim.eligibility or {}).get("operation") != "player_game_summary":
        return False
    if not expected_games or set(claim.game_ids or []) != expected_games:
        return False
    if claim.metric_id == GAME_SCORE_METRIC:
        return claim.subject_id == "team:NYK"
    if claim.metric_id not in GAME_SUMMARY_METRICS:
        return False
    return claim.subject_id in {f"player:{pid}" for pid in scope.player_ids}


def _leaderboard_claim_relevant(
    claim: VerifiedClaim, scope: object, expected_games: set[int]
) -> bool:
    """A leaderboard claim answers only the metric and population it ranked."""
    metric = getattr(scope, "metric", None) or "points"
    return (
        str(claim.subject_id or "").startswith("player:")
        and (claim.eligibility or {}).get("operation") == "player_leaderboard"
        and claim.metric_id == f"{metric}:leader"
        and _exact_population(claim, expected_games)
    )


def _exact_population(claim: VerifiedClaim, expected: set[int]) -> bool:
    """Whether a claim ranked or counted the complete authoritative population.

    A ranking or aggregate over a subset cannot answer a request for the whole
    population: a model call narrowed to January still proves only its January games.
    """
    considered = set((claim.eligibility or {}).get("considered_game_ids") or [])
    return bool(considered) and considered == expected


def _team_claim_relevant(
    claim: VerifiedClaim,
    *,
    operations: frozenset[str],
    expected_games: set[int],
    expected_considered: set[int] | None,
) -> bool:
    """Require the requested operation and its complete considered population."""
    if claim.subject_id != "team:NYK":
        return False
    eligibility = claim.eligibility or {}
    if eligibility.get("operation") not in operations:
        return False
    if expected_considered is None:
        # Swing rankings rank only the games with play-by-play margins, which cannot be
        # recomputed without a query; the operation and release checks still apply.
        return set(claim.game_ids or []) <= expected_games
    return _exact_population(claim, expected_considered)
