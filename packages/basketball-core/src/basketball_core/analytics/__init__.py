"""Canonical player-intelligence calculations and public domain types."""

from basketball_core.analytics.calculations import (
    aggregate_rows,
    count_double_doubles,
    linear_slope,
    robust_outlier_scores,
    rolling_mean,
)
from basketball_core.analytics.catalog import build_fact_catalog
from basketball_core.analytics.discovery import (
    DETECTOR_VERSION,
    FactCandidate,
    fact_fingerprint,
    rank_fact_candidates,
    score_fact_candidate,
)
from basketball_core.analytics.registry import STAT_REGISTRY, StatDefinition, resolve_stat
from basketball_core.analytics.types import (
    AnalyticsOperation,
    AnalyticsPlan,
    OutputType,
    ResolvedPlayer,
    Timeframe,
)

__all__ = [
    "AnalyticsOperation",
    "AnalyticsPlan",
    "DETECTOR_VERSION",
    "FactCandidate",
    "OutputType",
    "ResolvedPlayer",
    "STAT_REGISTRY",
    "StatDefinition",
    "Timeframe",
    "aggregate_rows",
    "build_fact_catalog",
    "count_double_doubles",
    "fact_fingerprint",
    "linear_slope",
    "rank_fact_candidates",
    "resolve_stat",
    "robust_outlier_scores",
    "rolling_mean",
    "score_fact_candidate",
]
