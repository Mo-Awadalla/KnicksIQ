"""Pure formulas shared by request-time and offline analytics."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from basketball_core.analytics.registry import STAT_REGISTRY


def _value(row: Mapping[str, Any] | Any, column: str) -> float:
    raw = row.get(column, 0) if isinstance(row, Mapping) else getattr(row, column, 0)
    return float(raw or 0)


def aggregate_rows(
    rows: Sequence[Mapping[str, Any] | Any], stat_keys: Sequence[str]
) -> dict[str, float | None]:
    """Aggregate appearances with weighted rates and total-minute per-36 values."""
    values: dict[str, float | None] = {}
    sample = len(rows)
    for key in stat_keys:
        definition = STAT_REGISTRY[key]
        totals = [sum(_value(row, column) for row in rows) for column in definition.columns]
        if definition.kind in {"count", "minutes"}:
            values[key] = totals[0] / sample if sample else None
        elif definition.kind == "percentage":
            values[key] = (100.0 * totals[0] / totals[1]) if totals[1] else None
        elif key == "true_shooting_percentage":
            denominator = 2.0 * (totals[1] + 0.44 * totals[2])
            values[key] = (100.0 * totals[0] / denominator) if denominator else None
        elif key == "effective_field_goal_percentage":
            values[key] = (100.0 * (totals[0] + 0.5 * totals[1]) / totals[2]) if totals[2] else None
        elif key == "assist_turnover_ratio":
            values[key] = totals[0] / totals[1] if totals[1] else None
        elif key.endswith("_per_36"):
            values[key] = (36.0 * totals[0] / totals[1]) if totals[1] else None
        elif key == "points_standard_deviation":
            values[key] = statistics.pstdev(_value(row, "points") for row in rows) if rows else None
        elif key == "points_floor":
            values[key] = min((_value(row, "points") for row in rows), default=None)
        elif key == "double_doubles":
            values[key] = float(sum(count_double_doubles(row)[0] for row in rows))
        elif key == "triple_doubles":
            values[key] = float(sum(count_double_doubles(row)[1] for row in rows))
        else:  # pragma: no cover - registry exhaustiveness guard
            raise KeyError(key)
    return values


def count_double_doubles(row: Mapping[str, Any] | Any) -> tuple[bool, bool]:
    qualifying = sum(
        _value(row, key) >= 10 for key in ("points", "rebounds", "assists", "steals", "blocks")
    )
    return qualifying >= 2, qualifying >= 3


def rolling_mean(values: Sequence[float], window: int = 5) -> list[float]:
    if window <= 0:
        raise ValueError("window must be positive")
    return [
        sum(values[max(0, index - window + 1) : index + 1]) / min(index + 1, window)
        for index in range(len(values))
    ]


def linear_slope(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    x_mean = (len(values) - 1) / 2
    y_mean = sum(values) / len(values)
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    return (
        sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values)) / denominator
        if denominator
        else None
    )


def robust_outlier_scores(values: Sequence[float]) -> list[float]:
    """Return signed robust scores using MAD, with an IQR fallback."""
    if not values:
        return []
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    mad = statistics.median(deviations)
    if mad:
        return [0.6745 * (value - median) / mad for value in values]
    if len(values) < 4:
        return [0.0 for _ in values]
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    iqr = quartiles[2] - quartiles[0]
    if not iqr or not math.isfinite(iqr):
        return [0.0 for _ in values]
    return [(value - median) / iqr for value in values]
