"""Build immutable notable-fact catalogs from release-bundle rows."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from basketball_core.analytics.calculations import aggregate_rows
from basketball_core.analytics.discovery import (
    DETECTOR_VERSION,
    FactCandidate,
    fact_fingerprint,
    score_fact_candidate,
)
from basketball_core.analytics.registry import STAT_REGISTRY

_DISCOVERY_STATS = ("points", "rebounds", "assists", "threes_made", "true_shooting_percentage")


def _candidate_row(candidate: FactCandidate, data_through: str) -> dict[str, Any]:
    score, components = score_fact_candidate(candidate)
    return {
        "fingerprint": fact_fingerprint(candidate),
        "fact_type": candidate.fact_type,
        "player_ids": list(candidate.player_ids),
        "stat_keys": list(candidate.stat_keys),
        "timeframe": candidate.timeframe,
        "statement": candidate.statement,
        "result": candidate.result,
        "source_game_ids": list(candidate.source_game_ids),
        "sample_size": candidate.sample_size,
        "total_score": score,
        "score_components": components,
        "detector_version": DETECTOR_VERSION,
        "data_through": data_through,
    }


def _windows(games: list[dict[str, Any]]) -> list[tuple[dict[str, Any], set[str]]]:
    ordered = sorted(games, key=lambda row: (row["game_date"], row["nba_game_id"]))
    regular = {row["nba_game_id"] for row in ordered if row.get("season_type") == "regular"}
    playoffs = {
        row["nba_game_id"] for row in ordered if row.get("season_type") in {"play_in", "playoffs"}
    }
    windows = [
        ({"kind": "regular_season", "label": "2025-26 regular season"}, regular),
        ({"kind": "playoffs", "label": "2025-26 playoffs"}, playoffs),
        (
            {"kind": "full_archive", "label": "full 2025-26 archive"},
            {row["nba_game_id"] for row in ordered},
        ),
        (
            {
                "kind": "last_n",
                "label": "latest 10 Knicks games",
                "last_n": 10,
                "unit": "archive_games",
            },
            {row["nba_game_id"] for row in ordered[-10:]},
        ),
    ]
    months: dict[str, set[str]] = defaultdict(set)
    for row in ordered:
        months[str(row["game_date"])[:7]].add(row["nba_game_id"])
    windows.extend(
        ({"kind": "month", "label": month}, game_ids) for month, game_ids in sorted(months.items())
    )
    return windows


def build_fact_catalog(
    games: list[dict[str, Any]],
    player_stats: list[dict[str, Any]],
    players: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create stable structured facts for every required immutable archive window."""
    if not games or not player_stats:
        return []
    names = {int(row["nba_player_id"]): str(row["full_name"]) for row in players}
    data_through = max(str(row["game_date"]) for row in games)
    output: list[dict[str, Any]] = []
    for timeframe, game_ids in _windows(games):
        window_rows = [
            row
            for row in player_stats
            if row.get("nba_game_id") in game_ids
            and row.get("team_id") == "NYK"
            and float(row.get("minutes") or 0) > 0
        ]
        by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in window_rows:
            by_player[int(row["nba_player_id"])].append(row)
        for stat in _DISCOVERY_STATS:
            eligible: list[tuple[float, int, list[dict[str, Any]]]] = []
            for player_id, rows in by_player.items():
                if stat == "true_shooting_percentage" and (
                    sum(float(row.get("field_goals_attempted") or 0) for row in rows) / len(rows)
                    < 5
                ):
                    continue
                value = aggregate_rows(rows, [stat])[stat]
                if value is None or len(rows) < 4:
                    continue
                eligible.append((value, player_id, rows))
            if not eligible:
                continue
            value, player_id, rows = sorted(eligible, key=lambda item: (-item[0], item[1]))[0]
            label = STAT_REGISTRY[stat].label.lower()
            candidate = FactCandidate(
                fact_type="window_leader",
                player_ids=(player_id,),
                stat_keys=(stat,),
                timeframe=timeframe,
                statement=(
                    f"{names.get(player_id, player_id)} led Knicks qualifiers in {label} "
                    f"for {timeframe['label']} at {value:.1f}."
                ),
                result={"value": value, "rank": 1},
                source_game_ids=tuple(row["nba_game_id"] for row in rows),
                sample_size=len(rows),
                components={
                    "magnitude": 0.65,
                    "rarity": 0.45,
                    "sample_quality": min(1.0, len(rows) / 20),
                    "recency": 1.0 if timeframe["kind"] == "last_n" else 0.6,
                    "coverage": 1.0,
                    "basketball_relevance": 0.9,
                    "novelty": 0.6,
                    "interpretability": 1.0,
                },
                penalties={
                    "inadequate_sample": 0.1 if len(rows) < 8 else 0.0,
                    "single_game_driven": (
                        0.1
                        if stat in {"points", "rebounds", "assists", "threes_made"}
                        and sum(float(row.get(STAT_REGISTRY[stat].columns[0]) or 0) for row in rows)
                        and max(float(row.get(STAT_REGISTRY[stat].columns[0]) or 0) for row in rows)
                        / sum(float(row.get(STAT_REGISTRY[stat].columns[0]) or 0) for row in rows)
                        > 0.4
                        else 0.0
                    ),
                    "incomplete_coverage": 0.0,
                    "duplicate": 0.0,
                },
            )
            output.append(_candidate_row(candidate, data_through))

    ordered_games = {row["nba_game_id"]: (row["game_date"], row["nba_game_id"]) for row in games}
    all_by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in player_stats:
        if row.get("team_id") == "NYK" and float(row.get("minutes") or 0) > 0:
            all_by_player[int(row["nba_player_id"])].append(row)
    for player_id, unordered in all_by_player.items():
        rows = sorted(unordered, key=lambda row: ordered_games[row["nba_game_id"]])
        recent = rows[-10:]
        prior = rows[:-10]
        if len(recent) < 4 or len(prior) < 4:
            continue
        timeframe = {
            "kind": "last_n",
            "label": f"{names.get(player_id, player_id)} latest 10 appearances",
            "last_n": 10,
            "unit": "appearances",
        }
        for stat in _DISCOVERY_STATS[:3]:
            recent_value = aggregate_rows(recent, [stat])[stat]
            prior_value = aggregate_rows(prior, [stat])[stat]
            if recent_value is None or prior_value is None:
                continue
            delta = recent_value - prior_value
            materiality = STAT_REGISTRY[stat].materiality
            if abs(delta) < materiality:
                continue
            direction = "more" if delta > 0 else "fewer"
            candidate = FactCandidate(
                fact_type="recent_vs_baseline",
                player_ids=(player_id,),
                stat_keys=(stat,),
                timeframe=timeframe,
                statement=(
                    f"{names.get(player_id, player_id)} averaged {abs(delta):.1f} {direction} "
                    f"{STAT_REGISTRY[stat].label.lower()} in his latest 10 appearances "
                    "than in his prior eligible appearances."
                ),
                result={"recent": recent_value, "prior": prior_value, "delta": delta},
                source_game_ids=tuple(row["nba_game_id"] for row in rows),
                sample_size=len(rows),
                components={
                    "magnitude": min(1.0, abs(delta) / (2 * materiality)),
                    "rarity": 0.6,
                    "sample_quality": min(1.0, len(rows) / 24),
                    "recency": 1.0,
                    "coverage": 1.0,
                    "basketball_relevance": 0.9,
                    "novelty": 0.85,
                    "interpretability": 1.0,
                },
                penalties={
                    "inadequate_sample": 0.0,
                    "single_game_driven": 0.0,
                    "incomplete_coverage": 0.0,
                    "duplicate": 0.0,
                },
            )
            output.append(_candidate_row(candidate, data_through))
    unique = {row["fingerprint"]: row for row in output}
    return sorted(
        unique.values(),
        key=lambda row: (row["timeframe"]["label"], -row["total_score"], row["fingerprint"]),
    )
