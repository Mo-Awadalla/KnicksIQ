"""Deterministic player-pattern candidate generation from structured rows."""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PatternFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_type: str
    player_id: int
    metric: str
    statement: str
    values: dict[str, float | int | str]
    sample_size: int
    date_start: str
    date_end: str
    game_ids: list[int]
    calculation_method: str
    qualified: bool
    qualification: str | None = None
    relevance_score: float = Field(ge=0)
    significance_score: float = Field(ge=0)

    @property
    def total_score(self) -> float:
        return self.relevance_score + self.significance_score


def _average(rows: list[dict[str, Any]], metric: str) -> float:
    return fmean(float(row[metric]) for row in rows) if rows else 0.0


def _split_value(row: dict[str, Any], field: str) -> Any:
    if field == "home_away":
        return row.get(field) or ("home" if row.get("home") else "away")
    if field == "game_result":
        return row.get(field) or ("W" if row.get("win") else "L")
    return row.get(field)


def _base(
    *,
    fact_type: str,
    player_id: int,
    metric: str,
    statement: str,
    values: dict[str, float | int | str],
    rows: list[dict[str, Any]],
    method: str,
    qualified: bool,
    qualification: str | None,
    relevance: float,
    significance: float,
) -> PatternFact:
    ordered = sorted(rows, key=lambda row: (str(row["date"]), int(row["game_id"])))
    return PatternFact(
        fact_type=fact_type,
        player_id=player_id,
        metric=metric,
        statement=statement,
        values=values,
        sample_size=len(rows),
        date_start=str(ordered[0]["date"]),
        date_end=str(ordered[-1]["date"]),
        game_ids=[int(row["game_id"]) for row in ordered],
        calculation_method=method,
        qualified=qualified,
        qualification=qualification,
        relevance_score=relevance,
        significance_score=significance,
    )


def generate_pattern_facts(
    rows: list[dict[str, Any]],
    *,
    player_id: int,
    metric: str,
    threshold: float | None = None,
    minimum_split_sample: int = 3,
) -> list[PatternFact]:
    """Generate reproducible candidates; never infer values from prose."""
    appearances = sorted(
        [
            row
            for row in rows
            if int(row["player_id"]) == player_id
            and bool(row.get("appeared", True))
            and row.get(metric) is not None
        ],
        key=lambda row: (str(row["date"]), int(row["game_id"])),
    )
    if not appearances:
        return []
    candidates: list[PatternFact] = []

    if len(appearances) >= 10:
        previous, recent = appearances[-10:-5], appearances[-5:]
        previous_average = _average(previous, metric)
        recent_average = _average(recent, metric)
        delta = recent_average - previous_average
        candidates.append(
            _base(
                fact_type="recent_vs_previous",
                player_id=player_id,
                metric=metric,
                statement=(
                    f"Last-five {metric} average {recent_average:.1f} versus "
                    f"{previous_average:.1f} in the previous five."
                ),
                values={
                    "recent_average": round(recent_average, 4),
                    "previous_average": round(previous_average, 4),
                    "delta": round(delta, 4),
                },
                rows=appearances[-10:],
                method="arithmetic_mean(last_5) - arithmetic_mean(previous_5)",
                qualified=True,
                qualification=None,
                relevance=1.0,
                significance=abs(delta) / max(abs(previous_average), 1.0),
            )
        )

    for split_name, field, left, right in (
        ("home_vs_road", "home_away", "home", "away"),
        ("wins_vs_losses", "game_result", "W", "L"),
    ):
        left_rows = [row for row in appearances if _split_value(row, field) == left]
        right_rows = [row for row in appearances if _split_value(row, field) == right]
        combined = [*left_rows, *right_rows]
        if not combined:
            continue
        qualified = min(len(left_rows), len(right_rows)) >= minimum_split_sample
        left_average = _average(left_rows, metric)
        right_average = _average(right_rows, metric)
        candidates.append(
            _base(
                fact_type=split_name,
                player_id=player_id,
                metric=metric,
                statement=(
                    f"{left} {metric} average {left_average:.1f} versus "
                    f"{right_average:.1f} {right}."
                ),
                values={
                    f"{left}_average": round(left_average, 4),
                    f"{right}_average": round(right_average, 4),
                    f"{left}_sample": len(left_rows),
                    f"{right}_sample": len(right_rows),
                },
                rows=combined,
                method=f"group_by({field}); arithmetic_mean({metric})",
                qualified=qualified,
                qualification=(
                    None
                    if qualified
                    else f"Each side requires at least {minimum_split_sample} appearances."
                ),
                relevance=0.9,
                significance=abs(left_average - right_average)
                / max(abs(left_average), abs(right_average), 1.0),
            )
        )

    threshold = float(threshold if threshold is not None else 20.0)
    qualifying = [float(row[metric]) >= threshold for row in appearances]
    longest = current = running = 0
    for qualifies in qualifying:
        running = running + 1 if qualifies else 0
        longest = max(longest, running)
    for qualifies in reversed(qualifying):
        if not qualifies:
            break
        current += 1
    candidates.append(
        _base(
            fact_type="threshold_and_streak",
            player_id=player_id,
            metric=metric,
            statement=(
                f"{sum(qualifying)} games at or above {threshold:g} {metric}; "
                f"current streak {current}, longest streak {longest}."
            ),
            values={
                "threshold": threshold,
                "qualifying_games": sum(qualifying),
                "current_streak": current,
                "longest_streak": longest,
            },
            rows=appearances,
            method=f"count({metric} >= threshold); consecutive_run_lengths",
            qualified=True,
            qualification=None,
            relevance=0.85,
            significance=sum(qualifying) / len(appearances),
        )
    )

    opponent_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in appearances:
        opponent = row.get("opponent_id") or row.get("opponent")
        if opponent:
            opponent_groups[str(opponent)].append(row)
    eligible = {
        opponent: group
        for opponent, group in opponent_groups.items()
        if len(group) >= minimum_split_sample
    }
    if eligible:
        opponent, group = max(
            eligible.items(),
            key=lambda item: (_average(item[1], metric), item[0]),
        )
        opponent_average = _average(group, metric)
        candidates.append(
            _base(
                fact_type="strongest_opponent_split",
                player_id=player_id,
                metric=metric,
                statement=(
                    f"Strongest eligible opponent split: {opponent}, "
                    f"{opponent_average:.1f} {metric} per appearance."
                ),
                values={"opponent_id": opponent, "average": round(opponent_average, 4)},
                rows=group,
                method=(
                    f"group_by(opponent_id); require n>={minimum_split_sample}; "
                    f"max(arithmetic_mean({metric}))"
                ),
                qualified=True,
                qualification=None,
                relevance=0.75,
                significance=opponent_average / max(_average(appearances, metric), 1.0),
            )
        )

    return sorted(candidates, key=lambda fact: (-fact.total_score, fact.fact_type))
