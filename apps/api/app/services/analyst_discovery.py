"""Analyst discovery."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.services.evidence_contracts import Candidate, Evidence, ToolResult, VerifiedClaim
from app.services.query_resolution import ResolvedQuery
from basketball_core.analytics.catalog import _windows, build_fact_catalog
from basketball_core.analytics.registry import STAT_REGISTRY

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools


def discover(tools: AnalystTools, scope: ResolvedQuery, games: list[Game]) -> ToolResult:
    if scope.opponent_id and not scope.player_ids:
        # Single-game highlights cannot answer a matchup question; force the record tools.
        return ToolResult(
            status="no_matching_results",
            message="Single-game examples do not summarize a matchup. Call get_team_stats "
            "for the opponent record and phase breakdown.",
            scope=scope.model_dump(mode="json"),
        )
    if scope.opponent_id and scope.player_ids:
        # A player-vs-opponent question needs every appearance, not the best single line.
        return ToolResult(
            status="no_matching_results",
            message="Single-game examples do not summarize a player matchup. Call "
            "get_player_stats for the full opponent population.",
            scope=scope.model_dump(mode="json"),
        )
    if re.search(
        r"\b(?:biggest|best|largest|worst|heaviest)\s+(?:win|victory|loss|defeat|blowout)\b"
        r"|\b(?:highest|most)[- ]scoring\b|\bmost points (?:in a game|scored)\b",
        tools.question,
        re.I,
    ):
        # Single-game highlights are not the team extreme the question asks for.
        return ToolResult(
            status="no_matching_results",
            message="Single-game highlights do not answer a team extreme. Call get_team_stats.",
            scope=scope.model_dump(mode="json"),
        )
    game_map = {g.id: g for g in games}
    seen = set(tools.state.get("delivered_fact_ids", []))
    excluded = set(tools.state.get("last_subjects", [])) if tools.different else set()
    pool: list[tuple[float, Candidate, list[VerifiedClaim], list[Evidence]]] = []
    for stat, player in tools.rows:
        subject = f"player:{player.id}"
        if stat.game_id not in game_map or stat.minutes <= 0 or subject in excluded:
            continue
        if scope.player_ids and player.id not in scope.player_ids:
            continue
        game = game_map[stat.game_id]
        opponent = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
        fact_id = f"{tools.release.version}:box:{game.id}:{player.id}"
        if fact_id in seen:
            continue
        receipt = tools.receipt(game, stat, player)
        requested_metric = scope.metric
        # Derived metrics (starts, percentages, double-doubles) have no stored column;
        # discovery reports the observed box-score line instead of inventing one.
        metric = "box_score"
        if requested_metric is not None and hasattr(stat, requested_metric):
            metric = requested_metric
        metrics = [metric]
        claims = []
        for metric in metrics:
            values = {
                key: getattr(stat, key) for key in ("points", "rebounds", "assists", "turnovers")
            }
            value = values if metric == "box_score" else getattr(stat, metric)
            line = (
                f"{stat.points} points, {stat.rebounds} rebounds, "
                f"{stat.assists} assists and {stat.turnovers} turnovers"
                if metric == "box_score"
                else f"{value} {metric}"
            )
            claims.append(
                tools.claim(
                    subject=subject,
                    metric=metric,
                    value=value,
                    unit="count by box-score metric" if metric == "box_score" else metric,
                    games=[game],
                    evidence=[receipt],
                    scope=scope,
                    sample=1,
                    denominator=None,
                    statement=f"{player.full_name} recorded {line} on {game.game_date} against "
                    f"{opponent}.",
                    limitations=[
                        "Observed appearance; no season or historical ranking.",
                        "Selected for a high box-score value; not proof of improvement.",
                    ],
                    eligibility={
                        "appearance": "minutes > 0",
                        "policy_version": "single-game-v1",
                    },
                )
            )
        candidate = Candidate(
            fact_id=fact_id,
            fact_family="single_game",
            subject_id=subject,
            metric=",".join(metrics),
            window={"game_ids": [game.id]},
            baseline=[],
            claim_ids=[c.claim_id for c in claims],
            selection_reason=(
                "High requested metric"
                if scope.metric
                else "High points + 1.5*assists + rebounds - turnovers"
            ),
            extreme_selected=True,
        )
        score = (
            getattr(stat, metric)
            if metric != "box_score"
            else stat.points + 1.5 * stat.assists + stat.rebounds - stat.turnovers
        )
        pool.append((score, candidate, claims, [receipt]))
    # Recompute the existing catalog from the COMPLETE release population. This retains
    # its eligibility rules and never mistakes retrieved examples for comparison baselines.
    game_all = {g.id: g for g in tools.games}
    catalog_rows = []
    players = {}
    for stat, player in tools.rows:
        if player.nba_player_id is None:
            continue
        players[player.nba_player_id] = player
        catalog_rows.append(
            {
                **{c.name: getattr(stat, c.name) for c in PlayerGameStat.__table__.columns},
                "nba_player_id": player.nba_player_id,
                "nba_game_id": game_all[stat.game_id].nba_game_id,
            }
        )
    catalog = build_fact_catalog(
        [
            {
                "nba_game_id": g.nba_game_id,
                "game_date": str(g.game_date),
                "season_type": g.season_type,
            }
            for g in tools.games
            if g.nba_game_id
        ],
        catalog_rows,
        [{"nba_player_id": key, "full_name": p.full_name} for key, p in players.items()],
    )
    by_source = {g.nba_game_id: g for g in games}
    rows_by_game_player = {(s.game_id, p.id): (s, p) for s, p in tools.rows}
    for fact in catalog:
        if fact["fingerprint"] in seen or not set(fact["source_game_ids"]) <= by_source.keys():
            continue
        player = players[fact["player_ids"][0]]
        subject = f"player:{player.id}"
        if subject in excluded or (scope.player_ids and player.id not in scope.player_ids):
            continue
        if scope.metric and scope.metric not in fact["stat_keys"]:
            continue
        selected = [by_source[key] for key in fact["source_game_ids"]]
        receipts = [
            tools.receipt(g, s, p)
            for g in selected
            if (g.id, player.id) in rows_by_game_player
            for s, p in [rows_by_game_player[(g.id, player.id)]]
        ]
        eligibility = {
            "policy_version": fact["detector_version"],
            "minimum_appearances": 4,
            "appearance": "minutes > 0",
            "true_shooting_minimum_fga_per_appearance": 5,
            "recent_window": 10,
            "prior_minimum_appearances": 4,
            "population": "Knicks qualifiers in complete release window",
        }
        metric = fact["stat_keys"][0]
        label = STAT_REGISTRY[metric].label.lower()
        unit = "percent" if "percentage" in metric else f"{label} per appearance"
        common: dict[str, Any] = dict(
            subject=subject,
            unit=unit,
            scope=scope,
            eligibility=eligibility,
            limitations=[
                "Available archive and stated qualifiers only.",
                "Extreme selection does not establish improvement or causation.",
            ],
        )
        fact_claims = []
        if fact["fact_type"] == "recent_vs_baseline":
            ordered = sorted(selected, key=lambda g: (g.game_date, g.nba_game_id))
            for key, subset in (("recent", ordered[-10:]), ("prior", ordered[:-10])):
                subset_ids = {g.id for g in subset}
                subset_receipts = [e for e in receipts if e.game_id in subset_ids]
                value = fact["result"][key]
                fact_claims.append(
                    tools.claim(
                        **common,
                        metric=metric + ":average",
                        value=value,
                        games=subset,
                        evidence=subset_receipts,
                        sample=len(subset),
                        denominator=len(subset),
                        window={"kind": key},
                        statement=f"{player.full_name}: {value:.1f} {unit} across "
                        f"{len(subset)} {key} observed appearances.",
                    )
                )
            baseline_ids = [c.claim_id for c in fact_claims]
            claim = tools.claim(
                **common,
                metric=metric + ":delta",
                value=fact["result"]["delta"],
                games=ordered,
                evidence=receipts,
                statement=fact["statement"],
                sample=len(ordered[-10:]),
                denominator=len(ordered[-10:]),
                baseline=baseline_ids,
                window=fact["timeframe"],
            )
            fact_claims.append(claim)
        else:
            # Rank depends on ALL qualifiers, including games the leader did not play.
            population_ids = next(
                ids
                for window, ids in _windows(
                    [
                        {
                            "nba_game_id": g.nba_game_id,
                            "game_date": str(g.game_date),
                            "season_type": g.season_type,
                        }
                        for g in tools.games
                        if g.nba_game_id
                    ]
                )
                if window == fact["timeframe"]
            )
            if not population_ids <= by_source.keys():
                continue
            population_games = [by_source[key] for key in sorted(population_ids)]
            population_rows = [
                (row, p)
                for row, p in tools.rows
                if game_all[row.game_id].nba_game_id in population_ids and row.minutes > 0
            ]
            # The original catalog qualifies players at four appearances, and TS at 5 FGA.
            qualifiers = {}
            for row, p in population_rows:
                qualifiers.setdefault(p.id, []).append(row)
            qualified = {
                pid
                for pid, rows in qualifiers.items()
                if len(rows) >= 4
                and (
                    metric != "true_shooting_percentage"
                    or sum(row.field_goals_attempted for row in rows) / len(rows) >= 5
                )
            }
            all_receipts = [
                tools.receipt(game_all[row.game_id], row, p)
                for row, p in population_rows
                if p.id in qualified
            ]
            value = fact["result"]["value"]
            average = tools.claim(
                **common,
                metric=metric + ":average",
                value=value,
                games=selected,
                evidence=receipts,
                sample=len(selected),
                denominator=len(selected),
                window=fact["timeframe"],
                statement=f"{player.full_name}: {value:.1f} {unit} across "
                f"{len(selected)} appearances in {fact['timeframe']['label']}.",
            )
            # Percentage calculations use shot opportunities, not appearances, as denominator.
            if metric == "true_shooting_percentage":
                subject_rows = [row for row, p in population_rows if p.id == player.id]
                denominator = 2 * (
                    sum(row.field_goals_attempted for row in subject_rows)
                    + 0.44 * sum(row.free_throws_attempted for row in subject_rows)
                )
                values = average.model_dump(exclude={"claim_id"})
                values["denominator"] = denominator
                tools.claims.pop(average.claim_id)
                average = VerifiedClaim.create(**values)
                tools.claims[average.claim_id] = average
            rank = tools.claim(
                subject=subject,
                metric=metric + ":qualifier_rank",
                value=1,
                unit="rank",
                games=population_games,
                evidence=all_receipts,
                statement=fact["statement"],
                scope=scope,
                sample=len(qualified),
                denominator=len(qualified),
                baseline=[average.claim_id],
                window=fact["timeframe"],
                eligibility=eligibility,
                population="all eligible Knicks players in complete catalog window",
            )
            fact_claims = [average, rank]
            claim = rank
        candidate = Candidate(
            fact_id=fact["fingerprint"],
            fact_family=fact["fact_type"],
            subject_id=subject,
            metric=metric,
            window=fact["timeframe"],
            baseline=claim.baseline_claim_ids,
            claim_ids=[c.claim_id for c in fact_claims],
            selection_reason="Existing catalog eligibility and magnitude.",
            extreme_selected=True,
        )
        support = list(
            {
                e.evidence_id: e
                for c in fact_claims
                for ref in c.supporting_evidence_ids
                for e in [tools.evidence[ref]]
            }.values()
        )
        pool.append((40 * fact["total_score"], candidate, fact_claims, support))
    families = set(tools.state.get("delivered_families", []))
    pool.sort(key=lambda row: (row[1].fact_family in families, -row[0], row[1].fact_id))
    chosen = pool[:10]
    for _, candidate, _, _ in chosen:
        tools.candidates[candidate.fact_id] = candidate
    return ToolResult(
        status="ok" if chosen else "no_matching_results",
        message="Choose a relevant candidate and explain its observed meaning."
        if chosen
        else "No undelivered eligible facts match this scope.",
        claims=[c for _, _, claims, _ in chosen for c in claims],
        evidence=list({e.evidence_id: e for _, _, _, es in chosen for e in es}.values()),
        candidates=[c for _, c, _, _ in chosen],
        scope=scope.model_dump(mode="json"),
    )
