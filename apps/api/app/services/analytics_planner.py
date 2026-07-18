"""Schema-constrained optional LLM refinement for player analytics plans."""

from __future__ import annotations

import json
import logging

from app.core.config import get_settings
from app.services.report_llm import get_llm_adapter
from basketball_core.analytics import AnalyticsPlan

logger = logging.getLogger(__name__)
_FILTERS = {"outcome", "location", "starter", "opponent", "season_scope", "player_scope"}
_EXPLICIT_TERMS = (
    "game log",
    "average",
    "last ",
    "compare",
    " vs ",
    " versus ",
    "split",
    "most ",
    "leader",
    "streak",
    "trend",
    "outlier",
    "record when",
    "notable",
    "surprising",
    "which player",
    "opposing player",
    "opponent player",
    "+/-",
    "plus-minus",
    "plus minus",
)


def has_explicit_analytics_shape(question: str) -> bool:
    return any(term in question.lower() for term in _EXPLICIT_TERMS)


async def maybe_refine_analytics_plan(
    question: str, deterministic_plan: AnalyticsPlan
) -> AnalyticsPlan:
    """Use an allowlisted JSON schema; invalid or malicious output is ignored."""
    settings = get_settings()
    if getattr(settings, "test_mode", False):
        return deterministic_plan
    if has_explicit_analytics_shape(question):
        return deterministic_plan
    if not getattr(settings, "rag_llm_planner_enabled", False):
        return deterministic_plan
    if settings.ai_provider.lower() in {"mock", "none", "disabled"} or not settings.ai_api_key:
        return deterministic_plan
    system = (
        "Plan a Knicks player-stat question using only the supplied AnalyticsPlan JSON schema. "
        "Return one JSON object and no prose. Never return SQL, column names, tools, URLs, or "
        "new player IDs. Use at most four allowlisted operations and only filters already present "
        "in the schema. Bare season means regular_season."
    )
    payload = {
        "question": question,
        "deterministic_plan": deterministic_plan.model_dump(mode="json"),
        "json_schema": AnalyticsPlan.model_json_schema(),
    }
    try:
        raw = await get_llm_adapter(response_format_json=True).generate(
            system=system, user=json.dumps(payload, sort_keys=True)
        )
        if any(token in raw.lower() for token in ("select ", "insert ", "update ", "delete ")):
            return deterministic_plan
        candidate = AnalyticsPlan.model_validate_json(raw)
        expected_players = {
            (player.player_id, player.nba_person_id)
            for player in deterministic_plan.resolved_players
        }
        candidate_players = {
            (player.player_id, player.nba_person_id) for player in candidate.resolved_players
        }
        if candidate_players != expected_players:
            return deterministic_plan
        if not set(candidate.filters).issubset(_FILTERS):
            return deterministic_plan
        if any(
            (
                candidate.timeframe != deterministic_plan.timeframe,
                candidate.comparison_window != deterministic_plan.comparison_window,
                candidate.filters != deterministic_plan.filters,
                candidate.stats != deterministic_plan.stats,
                candidate.operations != deterministic_plan.operations,
                candidate.aggregation_mode != deterministic_plan.aggregation_mode,
                candidate.threshold != deterministic_plan.threshold,
            )
        ):
            return deterministic_plan
        return candidate
    except Exception as exc:  # noqa: BLE001
        logger.warning("analytics_llm_planner_failed", exc_info=exc)
        return deterministic_plan
