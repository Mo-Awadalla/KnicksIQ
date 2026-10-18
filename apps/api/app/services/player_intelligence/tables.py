"""Tabular player aggregates, comparisons, splits and leaderboards."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from basketball_core.analytics import (
    STAT_REGISTRY,
    AnalyticsPlan,
    aggregate_rows,
)


def _display(stat: str, value: float | None) -> str:
    if value is None:
        return "—"
    definition = STAT_REGISTRY[stat]
    if definition.kind == "percentage" or stat.endswith("_percentage"):
        return f"{value:.1f}%"
    return f"{value:.{definition.decimals}f}"


def _aggregate_value_sets(
    plan: AnalyticsPlan, rows: list[dict[str, Any]]
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    averages = aggregate_rows(rows, plan.stats)
    totals: dict[str, float | None] = {}
    for key in plan.stats:
        definition = STAT_REGISTRY[key]
        if definition.kind in {"count", "minutes"}:
            totals[key] = sum(float(row.get(definition.columns[0], 0) or 0) for row in rows)
        else:
            # Rates remain weighted across the complete sample; per-36 uses total minutes.
            totals[key] = averages[key]
    return averages, totals


def _mode_values(
    plan: AnalyticsPlan, rows: list[dict[str, Any]]
) -> tuple[dict[str, float | None], dict[str, float | None], dict[str, float | None]]:
    averages, totals = _aggregate_value_sets(plan, rows)
    primary = totals if plan.aggregation_mode == "total" else averages
    return primary, averages, totals


def _common_result(
    result_type: str,
    title: str,
    plan: AnalyticsPlan,
    source_rows: list[dict[str, Any]],
    *,
    result_id: str = "result-1",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    source_ids = sorted({int(row["game_id"]) for row in source_rows})
    return {
        "id": result_id,
        "type": result_type,
        "title": title,
        "raw_values": {},
        "display_values": {},
        "sample_size": sum(bool(row["appeared"]) for row in source_rows),
        "timeframe": plan.timeframe.model_dump(mode="json"),
        "warnings": warnings or [],
        "source_game_ids": source_ids,
    }


def _aggregate_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    appearances = [row for row in rows if row["appeared"]]
    name = plan.resolved_players[0].full_name if plan.resolved_players else "Selected players"
    opponent = plan.filters.get("opponent")
    scope = f"{plan.timeframe.label} versus {opponent}" if opponent else plan.timeframe.label
    result = _common_result("aggregate", f"{name} — {scope}", plan, rows)
    values, averages, totals = _mode_values(plan, appearances)
    result["raw_values"] = values
    result["display_values"] = {key: _display(key, value) for key, value in values.items()}
    result["aggregation_mode"] = plan.aggregation_mode
    result["per_appearance_values"] = averages
    result["per_appearance_display_values"] = {
        key: _display(key, value) for key, value in averages.items()
    }
    result["totals"] = totals
    result["total_display_values"] = {key: _display(key, value) for key, value in totals.items()}
    for stat in plan.stats:
        attempts_column = None
        minimum = 0
        if stat in {
            "field_goal_percentage",
            "true_shooting_percentage",
            "effective_field_goal_percentage",
        }:
            attempts_column, minimum = "field_goals_attempted", 5
        elif stat == "three_point_percentage":
            attempts_column, minimum = "three_pointers_attempted", 2
        elif stat == "free_throw_percentage":
            attempts_column, minimum = "free_throws_attempted", 2
        if attempts_column and appearances:
            attempts = sum(float(row[attempts_column]) for row in appearances) / len(appearances)
            if attempts < minimum:
                result["warnings"].append(
                    f"Named-player result is below the {minimum} attempts-per-appearance "
                    "ranking threshold."
                )
    return result


def _game_log_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    appearances = [row for row in rows if row["appeared"]]
    name = plan.resolved_players[0].full_name if plan.resolved_players else "Player"
    result = _common_result("game_log", f"{name} game log", plan, rows)
    result["entries"] = [
        {
            "game_id": row["game_id"],
            "date": row["date"],
            "opponent": row["opponent"],
            "result": "W" if row["win"] else "L",
            "raw_values": {key: aggregate_rows([row], [key])[key] for key in plan.stats},
            "display_values": {
                key: _display(key, aggregate_rows([row], [key])[key]) for key in plan.stats
            },
        }
        for row in reversed(appearances)
    ]
    return result


def _comparison_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["appeared"]:
            groups[row["player_id"]].append(row)
    result = _common_result("player_comparison", "Player comparison", plan, rows)
    result["groups"] = []
    for player in plan.resolved_players:
        values, averages, totals = _mode_values(plan, groups[player.player_id])
        result["groups"].append(
            {
                "key": str(player.nba_person_id),
                "label": player.full_name,
                "sample_size": len(groups[player.player_id]),
                "raw_values": values,
                "display_values": {key: _display(key, value) for key, value in values.items()},
                "aggregation_mode": plan.aggregation_mode,
                "per_appearance_values": averages,
                "total_values": totals,
                "source_game_ids": sorted({row["game_id"] for row in groups[player.player_id]}),
            }
        )
        if len(groups[player.player_id]) < 4:
            result["warnings"].append(
                f"{player.full_name} has fewer than four appearances in the comparison."
            )
    return result


def _period_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    appearances = [row for row in rows if row["appeared"]]
    size = plan.timeframe.last_n or min(5, max(1, len(appearances) // 2))
    recent = appearances[-size:]
    prior = appearances[:-size]
    groups = [("Recent", recent), ("Prior baseline", prior)]
    title = "Recent appearances versus prior baseline"
    if plan.filters.get("comparison_window") == "all_star":
        groups = [
            ("Before All-Star break", [row for row in appearances if row["date"] <= "2026-02-15"]),
            ("After All-Star break", [row for row in appearances if row["date"] > "2026-02-15"]),
        ]
        title = "Before versus after the 2026 All-Star break"
    elif plan.filters.get("comparison_window") == "last_n_vs_season":
        groups = [(f"Last {size} appearances", recent), ("Full season", appearances)]
        title = "Recent appearances versus full season"
    result = _common_result("period_comparison", title, plan, rows)
    result["groups"] = []
    for label, group in groups:
        values, averages, totals = _mode_values(plan, group)
        result["groups"].append(
            {
                "key": label.lower().replace(" ", "_"),
                "label": label,
                "sample_size": len(group),
                "raw_values": values,
                "display_values": {key: _display(key, value) for key, value in values.items()},
                "aggregation_mode": plan.aggregation_mode,
                "per_appearance_values": averages,
                "total_values": totals,
                "source_game_ids": sorted({row["game_id"] for row in group}),
            }
        )
    if any(len(group) < 4 for _, group in groups):
        result["warnings"].append("Period comparisons need at least four appearances per side.")
    return result


def _split_result(plan: AnalyticsPlan, rows: list[dict[str, Any]], text: str) -> dict[str, Any]:
    if "home" in text.lower() or "away" in text.lower():
        keys = (("Home", lambda row: row["home"]), ("Away", lambda row: not row["home"]))
    elif "starter" in text.lower() or "bench" in text.lower():
        keys = (("Starter", lambda row: row["starter"]), ("Bench", lambda row: not row["starter"]))
    else:
        keys = (("Wins", lambda row: row["win"]), ("Losses", lambda row: not row["win"]))
    result = _common_result("split", "Player split", plan, rows)
    result["groups"] = []
    for label, predicate in keys:
        group = [row for row in rows if row["appeared"] and predicate(row)]
        values, averages, totals = _mode_values(plan, group)
        result["groups"].append(
            {
                "key": label.lower(),
                "label": label,
                "sample_size": len(group),
                "raw_values": values,
                "display_values": {key: _display(key, value) for key, value in values.items()},
                "aggregation_mode": plan.aggregation_mode,
                "per_appearance_values": averages,
                "total_values": totals,
                "source_game_ids": sorted({row["game_id"] for row in group}),
            }
        )
        if len(group) < 4:
            result["warnings"].append(f"{label} has fewer than four appearances.")
    return result


def _leaderboard_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    opponent_scope = plan.filters.get("player_scope") == "opponents"
    eligible_rows = [
        row
        for row in rows
        if row["appeared"]
        and ((row["team_id"] != "NYK") if opponent_scope else (row["team_id"] == "NYK"))
    ]
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible_rows:
        groups[row["player_id"]].append(row)
    stat = plan.stats[0]
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    for player_rows in groups.values():
        values, averages, totals = _mode_values(plan, player_rows)
        eligible = True
        attempts = 0.0
        if stat in {
            "field_goal_percentage",
            "true_shooting_percentage",
            "effective_field_goal_percentage",
        }:
            attempts = sum(row["field_goals_attempted"] for row in player_rows) / len(player_rows)
            eligible = attempts >= 5
        elif stat == "three_point_percentage":
            attempts = sum(row["three_pointers_attempted"] for row in player_rows) / len(
                player_rows
            )
            eligible = attempts >= 2
        elif stat == "free_throw_percentage":
            attempts = sum(row["free_throws_attempted"] for row in player_rows) / len(player_rows)
            eligible = attempts >= 2
        if not eligible or values[stat] is None:
            continue
        entries.append(
            {
                "player_id": player_rows[0]["nba_person_id"],
                "player_name": player_rows[0]["player_name"],
                "sample_size": len(player_rows),
                "raw_values": values,
                "display_values": {key: _display(key, value) for key, value in values.items()},
                "aggregation_mode": plan.aggregation_mode,
                "per_appearance_values": averages,
                "total_values": totals,
                "source_game_ids": sorted({row["game_id"] for row in player_rows}),
                "eligibility_attempts_per_appearance": attempts or None,
            }
        )
    entries.sort(key=lambda item: (-(item["raw_values"][stat] or 0), item["player_name"]))
    if not entries:
        warnings.append("No players met the requested ranking eligibility in this window.")
    result = _common_result(
        "leaderboard",
        (
            f"Opponent cumulative {STAT_REGISTRY[stat].label} leaders against the Knicks"
            if opponent_scope and plan.aggregation_mode == "total"
            else f"Knicks {STAT_REGISTRY[stat].label} leaders"
        ),
        plan,
        eligible_rows,
        warnings=warnings,
    )
    result["stat"] = stat
    result["aggregation_mode"] = plan.aggregation_mode
    result["player_scope"] = "opponents" if opponent_scope else "knicks"
    result["entries"] = entries[:10]
    if entries:
        result["source_game_ids"] = entries[0]["source_game_ids"]
        result["sample_size"] = entries[0]["sample_size"]
    return result
