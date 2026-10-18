"""Player streaks, trends, outliers, associations and notable facts."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from app.models.game import Game
from app.models.generated_stat_fact import GeneratedStatFact
from app.services.player_intelligence.tables import (
    _common_result,
    _display,
)
from basketball_core.analytics import (
    STAT_REGISTRY,
    AnalyticsPlan,
    FactCandidate,
    aggregate_rows,
    fact_fingerprint,
    linear_slope,
    rank_fact_candidates,
    robust_outlier_scores,
    rolling_mean,
    score_fact_candidate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _streak_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    stat = plan.stats[0]
    threshold = plan.threshold if plan.threshold is not None else STAT_REGISTRY[stat].materiality
    appearances = [row for row in rows if row["appeared"]]
    streaks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for row in appearances:
        value = aggregate_rows([row], [stat])[stat]
        if value is not None and value >= threshold:
            current.append(row)
        elif current:
            streaks.append(current)
            current = []
    if current:
        streaks.append(current)
    best = max(streaks, key=lambda group: (len(group), group[-1]["date"]), default=[])
    result = _common_result(
        "streak",
        f"Games with at least {_display(stat, threshold)} {STAT_REGISTRY[stat].label.lower()}",
        plan,
        best,
    )
    result["stat"] = stat
    result["threshold"] = threshold
    result["length"] = len(best)
    result["start_date"] = best[0]["date"] if best else None
    result["end_date"] = best[-1]["date"] if best else None
    return result


def _trend_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    stat = plan.stats[0]
    appearances = [row for row in rows if row["appeared"]]
    values = [float(aggregate_rows([row], [stat])[stat] or 0) for row in appearances]
    recent = appearances[-5:]
    prior = appearances[:-5]
    recent_value = aggregate_rows(recent, [stat])[stat]
    prior_value = aggregate_rows(prior, [stat])[stat]
    delta = (
        recent_value - prior_value if recent_value is not None and prior_value is not None else None
    )
    warnings = []
    if len(appearances) < 8:
        warnings.append("Trend interpretation needs at least eight appearances.")
    meaningful = bool(
        delta is not None
        and abs(delta) >= STAT_REGISTRY[stat].materiality
        and len(appearances) >= 8
    )
    result = _common_result(
        "trend", f"{STAT_REGISTRY[stat].label} trend", plan, appearances, warnings=warnings
    )
    result.update(
        {
            "stat": stat,
            "series": [
                {
                    "game_id": row["game_id"],
                    "date": row["date"],
                    "value": value,
                    "rolling_mean": mean,
                }
                for row, value, mean in zip(appearances, values, rolling_mean(values), strict=True)
            ],
            "slope": linear_slope(values),
            "recent_value": recent_value,
            "prior_value": prior_value,
            "delta": delta,
            "meaningful": meaningful,
        }
    )
    return result


def _outlier_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    stat = plan.stats[0]
    appearances = [row for row in rows if row["appeared"]]
    values = [float(aggregate_rows([row], [stat])[stat] or 0) for row in appearances]
    scores = robust_outlier_scores(values)
    ranked = sorted(
        zip(appearances, values, scores, strict=True), key=lambda item: (-abs(item[2]), -item[1])
    )
    selected = ranked[:3]
    warnings = []
    if len(appearances) < 10:
        warnings.append("Outlier detection needs a baseline of at least ten appearances.")
    result = _common_result(
        "outlier",
        f"{STAT_REGISTRY[stat].label} outliers",
        plan,
        appearances,
        warnings=warnings,
    )
    result["sample_size"] = len(appearances)
    result["candidate_count"] = len(selected)
    result["stat"] = stat
    result["entries"] = [
        {
            "game_id": row["game_id"],
            "date": row["date"],
            "opponent": row["opponent"],
            "value": value,
            "display_value": _display(stat, value),
            "robust_score": score,
        }
        for row, value, score in selected
    ]
    return result


def _outcome_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    stat = plan.stats[0]
    threshold = plan.threshold if plan.threshold is not None else 20.0
    appearances = [row for row in rows if row["appeared"]]
    qualifying = [
        row for row in appearances if float(aggregate_rows([row], [stat])[stat] or 0) >= threshold
    ]
    other = [row for row in appearances if row not in qualifying]
    warnings = ["This describes association, not causation or statistical significance."]
    if len(appearances) < 12:
        warnings.append("Outcome association needs at least twelve appearances.")

    def record(group: list[dict[str, Any]]) -> dict[str, int]:
        wins = sum(row["win"] for row in group)
        return {"wins": wins, "losses": len(group) - wins, "games": len(group)}

    result = _common_result(
        "outcome_association",
        f"Team record by {STAT_REGISTRY[stat].label.lower()} threshold",
        plan,
        appearances,
        warnings=warnings,
    )
    result.update(
        {
            "stat": stat,
            "threshold": threshold,
            "qualifying": record(qualifying),
            "other": record(other),
        }
    )
    return result


def _facts_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["appeared"] and row["team_id"] == "NYK":
            by_player[row["player_id"]].append(row)
    candidates: list[FactCandidate] = []
    for player_rows in by_player.values():
        if len(player_rows) < 8:
            continue
        recent = player_rows[-5:]
        prior = player_rows[:-5]
        for stat in plan.stats or ["points", "rebounds", "assists"]:
            recent_value = aggregate_rows(recent, [stat])[stat]
            prior_value = aggregate_rows(prior, [stat])[stat]
            if recent_value is None or prior_value is None:
                continue
            delta = recent_value - prior_value
            materiality = max(STAT_REGISTRY[stat].materiality, 0.1)
            if abs(delta) < materiality:
                continue
            name = player_rows[0]["player_name"]
            direction = "more" if delta > 0 else "fewer"
            statement = (
                f"{name} averaged {abs(delta):.1f} {direction} "
                f"{STAT_REGISTRY[stat].label.lower()} over his latest five "
                "appearances than before that window."
            )
            candidates.append(
                FactCandidate(
                    fact_type="recent_vs_baseline",
                    player_ids=(player_rows[0]["nba_person_id"],),
                    stat_keys=(stat,),
                    timeframe=plan.timeframe.model_dump(mode="json"),
                    statement=statement,
                    result={"recent": recent_value, "prior": prior_value, "delta": delta},
                    source_game_ids=tuple(row["game_id"] for row in player_rows),
                    sample_size=len(player_rows),
                    components={
                        "magnitude": min(1.0, abs(delta) / (2 * materiality)),
                        "rarity": 0.5,
                        "sample_quality": min(1.0, len(player_rows) / 20),
                        "recency": 1.0,
                        "coverage": 1.0,
                        "basketball_relevance": 0.8,
                        "novelty": 0.8,
                        "interpretability": 1.0,
                    },
                    penalties={"small_sample": 0.1 if len(prior) < 4 else 0},
                )
            )
    selected = rank_fact_candidates(candidates)
    source_rows = [
        row
        for row in rows
        if row["game_id"]
        in {game_id for candidate in selected for game_id in candidate.source_game_ids}
    ]
    result = _common_result(
        "notable_facts",
        "Exploratory notable facts",
        plan,
        source_rows,
        warnings=["Discovery is exploratory and bounded to the resolved archive window."],
    )
    result["facts"] = []
    for candidate in selected:
        score, components = score_fact_candidate(candidate)
        result["facts"].append(
            {
                "fingerprint": fact_fingerprint(candidate),
                "statement": candidate.statement,
                "fact_type": candidate.fact_type,
                "player_ids": list(candidate.player_ids),
                "stat_keys": list(candidate.stat_keys),
                "result": candidate.result,
                "sample_size": candidate.sample_size,
                "score": score,
                "score_components": components,
                "source_game_ids": list(candidate.source_game_ids),
            }
        )
    return result


async def _precomputed_facts_result(
    db: AsyncSession,
    release_id: int | None,
    plan: AnalyticsPlan,
    games: list[Game],
) -> dict[str, Any] | None:
    if release_id is None:
        return None
    timeframe = plan.timeframe
    is_catalog_window = timeframe.kind in {"regular_season", "playoffs", "full_archive"} or (
        timeframe.kind == "last_n" and timeframe.last_n == 10
    )
    if not is_catalog_window:
        return None
    facts = list(
        (
            await db.execute(
                select(GeneratedStatFact)
                .where(GeneratedStatFact.release_id == release_id)
                .order_by(GeneratedStatFact.total_score.desc(), GeneratedStatFact.fingerprint)
                .limit(200)
            )
        ).scalars()
    )
    requested_players = {player.nba_person_id for player in plan.resolved_players}
    selected: list[tuple[GeneratedStatFact, dict[str, Any], list[int], list[str]]] = []
    seen: set[tuple[tuple[int, ...], tuple[str, ...], str]] = set()
    for fact in facts:
        fact_timeframe = json.loads(fact.timeframe_json)
        if timeframe.kind == "last_n":
            if fact_timeframe.get("kind") != "last_n" or fact_timeframe.get("last_n") != 10:
                continue
            if fact_timeframe.get("unit") != timeframe.unit:
                continue
        elif fact_timeframe.get("kind") != timeframe.kind:
            continue
        player_ids = [int(value) for value in json.loads(fact.player_ids_json)]
        if requested_players and not requested_players.intersection(player_ids):
            continue
        stat_keys = [str(value) for value in json.loads(fact.stat_keys_json)]
        if plan.stats and not set(plan.stats).intersection(stat_keys):
            continue
        key = (tuple(sorted(player_ids)), tuple(sorted(stat_keys)), fact.fact_type)
        if key in seen:
            continue
        selected.append((fact, fact_timeframe, player_ids, stat_keys))
        seen.add(key)
        if len(selected) == 3:
            break
    if not selected:
        return None
    game_ids_by_source = {str(game.nba_game_id): game.id for game in games}
    source_rows: list[dict[str, Any]] = []
    result = _common_result(
        "notable_facts",
        "Exploratory notable facts",
        plan,
        source_rows,
        warnings=["Discovery is exploratory and bounded to the resolved archive window."],
    )
    result["facts"] = []
    all_source_ids: set[int] = set()
    for fact, fact_timeframe, player_ids, stat_keys in selected:
        source_ids = [
            game_ids_by_source[str(value)]
            for value in json.loads(fact.source_game_ids_json)
            if str(value) in game_ids_by_source
        ]
        all_source_ids.update(source_ids)
        result["facts"].append(
            {
                "fingerprint": fact.fingerprint,
                "statement": fact.statement,
                "fact_type": fact.fact_type,
                "player_ids": player_ids,
                "stat_keys": stat_keys,
                "timeframe": fact_timeframe,
                "result": json.loads(fact.result_json),
                "sample_size": fact.sample_size,
                "score": fact.total_score,
                "score_components": json.loads(fact.score_components_json),
                "source_game_ids": source_ids,
            }
        )
    result["source_game_ids"] = sorted(all_source_ids)
    result["sample_size"] = max(fact.sample_size for fact, *_ in selected)
    return result
