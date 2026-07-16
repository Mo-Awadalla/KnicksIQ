"""Public typed analytics response contract."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsClarificationChoice(BaseModel):
    id: str
    label: str
    value: str


class AnalyticsClarification(BaseModel):
    prompt: str
    choices: list[AnalyticsClarificationChoice]


class AnalyticsCoverage(BaseModel):
    expected_game_count: int
    covered_game_count: int
    missing_game_ids: list[int]
    completeness: float
    data_through: str | None


class ConsumerAnalyticsPlan(BaseModel):
    players: list[dict[str, Any]]
    timeframe: dict[str, Any]
    filters: dict[str, str | int | bool]
    stats: list[str]
    operations: list[str]
    output_type: str
    aggregation_mode: Literal["average", "total", "both"]
    retrieval_required: bool


class AnalyticsResultBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    raw_values: dict[str, float | None]
    display_values: dict[str, str]
    sample_size: int
    timeframe: dict[str, Any]
    warnings: list[str]
    source_game_ids: list[int]


class GameLogResult(AnalyticsResultBase):
    type: Literal["game_log"]


class AggregateResult(AnalyticsResultBase):
    type: Literal["aggregate"]


class PeriodComparisonResult(AnalyticsResultBase):
    type: Literal["period_comparison"]


class PlayerComparisonResult(AnalyticsResultBase):
    type: Literal["player_comparison"]


class SplitResult(AnalyticsResultBase):
    type: Literal["split"]


class LeaderboardResult(AnalyticsResultBase):
    type: Literal["leaderboard"]


class StreakResult(AnalyticsResultBase):
    type: Literal["streak"]


class TrendResult(AnalyticsResultBase):
    type: Literal["trend"]


class OutlierResult(AnalyticsResultBase):
    type: Literal["outlier"]


class OutcomeAssociationResult(AnalyticsResultBase):
    type: Literal["outcome_association"]


class NotableFactsResult(AnalyticsResultBase):
    type: Literal["notable_facts"]


AnalyticsResult = Annotated[
    GameLogResult
    | AggregateResult
    | PeriodComparisonResult
    | PlayerComparisonResult
    | SplitResult
    | LeaderboardResult
    | StreakResult
    | TrendResult
    | OutlierResult
    | OutcomeAssociationResult
    | NotableFactsResult,
    Field(discriminator="type"),
]


class AnalyticsPayload(BaseModel):
    status: Literal["complete", "clarification_required", "limited"]
    resolved_question: str
    plan: ConsumerAnalyticsPlan | None
    clarification: AnalyticsClarification | None
    results: list[AnalyticsResult]
    coverage: AnalyticsCoverage | None
