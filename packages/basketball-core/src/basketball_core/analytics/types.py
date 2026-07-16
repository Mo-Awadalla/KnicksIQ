"""Strict, storage-independent analytics plan types."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from basketball_core.analytics.registry import STAT_REGISTRY


class AnalyticsOperation(str, Enum):
    GAME_LOG = "game_log"
    AGGREGATE = "aggregate"
    PERIOD_COMPARISON = "period_comparison"
    PLAYER_COMPARISON = "player_comparison"
    SPLIT = "split"
    LEADERBOARD = "leaderboard"
    STREAK = "streak"
    TREND = "trend"
    OUTLIER = "outlier"
    OUTCOME_ASSOCIATION = "outcome_association"
    NOTABLE_FACTS = "notable_facts"


class OutputType(str, Enum):
    TABLE = "table"
    COMPARISON = "comparison"
    CHART = "chart"
    FACTS = "facts"


AggregationMode = Literal["average", "total", "both"]


class ResolvedPlayer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    player_id: int
    nba_person_id: int
    full_name: str


class Timeframe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["regular_season", "playoffs", "full_archive", "last_n", "date_range", "month"] = (
        "regular_season"
    )
    label: str = "2025-26 regular season"
    last_n: int | None = Field(default=None, ge=1, le=101)
    unit: Literal["archive_games", "appearances"] = "archive_games"
    start_date: str | None = None
    end_date: str | None = None


class AnalyticsPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolved_players: list[ResolvedPlayer] = Field(default_factory=list, max_length=8)
    timeframe: Timeframe = Field(default_factory=Timeframe)
    comparison_window: Timeframe | None = None
    filters: dict[str, str | int | bool] = Field(default_factory=dict)
    stats: list[str] = Field(default_factory=lambda: ["points"], min_length=1, max_length=8)
    operations: list[AnalyticsOperation] = Field(min_length=1, max_length=4)
    output_type: OutputType = OutputType.TABLE
    aggregation_mode: AggregationMode = "average"
    retrieval_required: bool = False
    ambiguities: list[str] = Field(default_factory=list)
    threshold: float | None = None

    @field_validator("stats")
    @classmethod
    def known_stats(cls, values: list[str]) -> list[str]:
        unknown = sorted(set(values) - set(STAT_REGISTRY))
        if unknown:
            raise ValueError(f"unknown canonical stats: {', '.join(unknown)}")
        return list(dict.fromkeys(values))
