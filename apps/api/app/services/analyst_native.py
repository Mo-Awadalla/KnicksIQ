"""Native statistic selection and claim-coverage requirements."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from app.services.analyst_fallback import re_search_discovery
from app.services.evidence_contracts import PLAYER_METRICS, VerifiedClaim
from app.services.player_threshold_games import is_player_threshold_question
from app.services.population_facts import is_player_leader_request
from app.services.query_parsing import is_game_score_request, is_record_request

if TYPE_CHECKING:
    from app.services.analyst_loop import AnalystLoop


def paired_record_claims(loop: AnalystLoop) -> list[VerifiedClaim]:
    if (
        loop.tools.scope is None
        or loop.tools.scope.player_ids
        or not is_record_request(loop.tools.question)
    ):
        return []
    claims = [claim for claim in loop.fallback_claims() if claim.metric_id in {"wins", "losses"}]
    return claims if {claim.metric_id for claim in claims} == {"wins", "losses"} else []


def native_statistic_tool(
    loop: AnalystLoop,
) -> Literal["get_player_stats", "get_team_stats", "find_player_games"] | None:
    """Prepare only calculations whose aggregation/populations are native and explicit."""
    scope = loop.tools.scope
    question = loop.tools.question
    if (
        scope is None
        or scope.requires_clarification
        or loop.tools.narrative
        or re_search_discovery(question)
        or re.search(r"\bscoring[ -]run\b", question, re.I)
        or loop.tools.season != loop.tools.release.season
        or any(
            s != loop.tools.release.season
            for s in re.findall(r"\b20\d{2}-\d{2}(?!-\d{2})\b", question)
        )
    ):
        return None
    team_groups = loop.tools.requested_team_groups()
    comparison = bool(
        re.search(
            r"\b(?:compare|compared|comparison|versus|vs|better|stronger|change|"
            r"differences?|differ(?:ed|s)?)\b"
            r"|\bbefore\b.*\bafter\b",
            question,
            re.I,
        )
    )
    if scope.periods:
        return (
            "get_team_stats"
            if loop.tools.supports_period_average(scope)
            and not team_groups
            and not (
                comparison
                and (
                    scope.date_start
                    or scope.date_end
                    or re.search(r"\bbefore\b.*\bafter\b", question, re.I)
                )
            )
            else None
        )
    if scope.player_ids and is_player_threshold_question(question):
        return "find_player_games"
    season_comparison = loop.tools.season_window_comparison_requested()
    player_comparison = bool(
        scope.player_ids
        and (
            season_comparison
            or re.search(r"\bbefore\s+and\s+after\s+(?:the\s+)?all[ -]star\b", question, re.I)
            or (
                comparison
                and len(scope.player_ids) > 1
                and not (scope.date_start or scope.date_end or scope.relative_game_count)
                and not re.search(r"\bbefore\b.*\bafter\b", question, re.I)
            )
        )
    )
    opponent_filter = bool(
        scope.opponent_id
        and not re.search(
            r"\b(?:compare|compared|comparison|differences?|differ(?:ed|s)?|change)\b"
            r"|\bbefore\b.*\bafter\b",
            question,
            re.I,
        )
    )
    if comparison and not (team_groups or player_comparison or opponent_filter):
        return None
    score_average = bool(re.search(r"\baverage scores?\b|\bscores? per game\b", question, re.I))
    if (
        scope.player_ids
        and not comparison
        and scope.requested_metrics
        and set(scope.requested_metrics) <= set(PLAYER_METRICS)
        and (len(scope.requested_metrics) > 1 or len(scope.requested_aggregations) > 1)
    ):
        return "get_player_stats"
    if scope.player_ids:
        opponent_profile = bool(
            not (scope.metric or scope.requested_metrics)
            and opponent_filter
            and re.search(r"^\s*(?:tell me about\b|how did\b|did\b.*\bplay well\b)", question, re.I)
        )
        metric = scope.metric or (
            "points" if season_comparison or opponent_profile or score_average else None
        )
        explicit_aggregation = re.search(
            r"\b(?:total|average|avg|per[ -]game|per[ -]appearance)\b", question, re.I
        )
        return (
            "get_player_stats"
            if loop.tools.player_profile_requested()
            or (
                metric in PLAYER_METRICS
                and (
                    explicit_aggregation
                    or player_comparison
                    or opponent_profile
                    or metric in {"double_doubles", "starts", "three_point_percentage"}
                )
            )
            else None
        )
    if team_groups:
        if scope.metric not in {None, "points", "turnovers"}:
            return None
        if re.search(r"\b(?:total|sum)\b", question, re.I) and not set(
            loop.tools.team_comparison_metrics(scope)
        ) <= {"games", "wins", "losses"}:
            return None
        return "get_team_stats"
    if is_player_leader_request(question):
        return "get_team_stats" if (scope.metric or "points") in PLAYER_METRICS else None
    if scope.metric not in {None, "points"}:
        return None
    if re.search(r"\b(?:total|sum)\b", question, re.I) and re.search(
        r"\b(?:allow(?:ed)?|opponents?)\b", question, re.I
    ):
        return None
    return (
        "get_team_stats"
        if is_record_request(question)
        or is_game_score_request(question)
        or scope.metric == "points"
        or score_average
        or re.search(
            r"\bhow many\b.*\b(?:games?|wins?|won|lose|losses|lost)\b"
            r"|\bmargin\b|\bpoints allowed\b",
            question,
            re.I,
        )
        else None
    )


def required_claim_groups(loop: AnalystLoop) -> dict[str, list[set[str]]]:
    """Project existing coverage policy; a group allows every matching native ID."""
    requirements = {}
    record = paired_record_claims(loop)
    if record:
        requirements["record"] = [{claim.claim_id} for claim in record]
    scope = loop.tools.scope
    if (
        scope is not None
        and scope.player_ids
        and not (scope.metric or scope.requested_metrics)
        and loop.tools.player_profile_requested()
    ):
        requirements["profile"] = [{claim.claim_id} for claim in loop.fallback_claims()]
    if scope is not None and not scope.player_ids and loop.tools.requested_team_groups():
        requirements["team"] = [{claim.claim_id} for claim in loop.fallback_claims()]
    if loop.tools.statistical_extreme_requested():
        assert loop.tools.narrative is not None
        metrics = {"game_score"}
        if "margin" in loop.tools.question.lower():
            metrics.add("margin")
        pairs = sorted(
            (metric, game.id) for metric in metrics for game in loop.tools.narrative.games
        )
        requirements["extreme"] = [
            {
                claim.claim_id
                for claim in loop.tools.claims.values()
                if claim.subject_id == "team:NYK"
                and claim.metric_id == metric
                and claim.game_ids == [game_id]
            }
            for metric, game_id in pairs
        ]
    if not requirements and native_statistic_tool(loop) is not None:
        statistics = loop.fallback_claims()
        if statistics:
            requirements["statistics"] = [{claim.claim_id} for claim in statistics]
    return requirements
