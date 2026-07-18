"""Schema-constrained planning for LLM-first archive retrieval."""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from app.core.config import get_settings
from app.services.report_llm import get_llm_adapter
from app.services.runtime_store import reserve_ai_budget
from app.services.team_aliases import team_ids_in_text
from pydantic import BaseModel, ConfigDict, Field

ArchiveCollection = Literal["games", "box_scores", "reports", "possessions"]
FactTool = Literal["table_rag", "player_analytics"]
logger = logging.getLogger(__name__)


class RetrievalPlanFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dates: list[str] = Field(default_factory=list, max_length=8)
    team_ids: list[str] = Field(default_factory=list, max_length=4)
    player_ids: list[int] = Field(default_factory=list, max_length=8)
    game_ids: list[int] = Field(default_factory=list, max_length=82)
    periods: list[int] = Field(default_factory=list, max_length=5)
    season_types: list[Literal["regular", "play_in", "playoffs"]] = Field(
        default_factory=list,
        max_length=3,
    )


class RetrievalPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported: bool
    intent: str = Field(min_length=1, max_length=80)
    queries: list[str] = Field(min_length=1, max_length=3)
    collections: list[ArchiveCollection] = Field(min_length=1, max_length=4)
    filters: RetrievalPlanFilters = Field(default_factory=RetrievalPlanFilters)
    fact_tools: list[FactTool] = Field(default_factory=list, max_length=2)


def deterministic_retrieval_plan(
    question: str,
    *,
    intent: str,
    is_aggregative: bool,
) -> RetrievalPlan:
    """Build the safe plan used when model planning is disabled or rejected."""
    lowered = question.lower()
    team_ids = sorted(team_ids_in_text(question) - {"NYK"})
    dates = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", question)
    periods = [int(value) for value in re.findall(r"\b(?:q|quarter\s*)([1-9])\b", lowered)]
    collections: list[ArchiveCollection] = ["games", "reports"]
    if is_aggregative or any(
        term in lowered
        for term in (
            "points",
            "scoring",
            "rebounds",
            "assists",
            "turnovers",
            "box score",
        )
    ):
        collections.append("box_scores")
    if not is_aggregative or any(
        term in lowered
        for term in ("swing", "run", "stretch", "quarter", "lead", "comeback", "play")
    ):
        collections.append("possessions")
    return RetrievalPlan(
        supported=True,
        intent=intent,
        queries=[question],
        collections=list(dict.fromkeys(collections)),
        filters=RetrievalPlanFilters(
            dates=dates,
            team_ids=team_ids,
            periods=periods,
        ),
        fact_tools=["table_rag"] if is_aggregative or "swing" in lowered else [],
    )


def _filters_are_grounded(plan: RetrievalPlan, question: str) -> bool:
    lowered = question.lower()
    allowed_teams = team_ids_in_text(question) | {"NYK"}
    if not set(plan.filters.team_ids).issubset(allowed_teams):
        return False
    allowed_dates = set(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", question))
    if not set(plan.filters.dates).issubset(allowed_dates):
        return False
    allowed_periods = {
        int(value) for value in re.findall(r"\b(?:q|quarter\s*)([1-9])\b", question.lower())
    }
    if not set(plan.filters.periods).issubset(allowed_periods):
        return False
    allowed_season_types: set[str] = set()
    if re.search(r"\bregular[- ]season\b", lowered):
        allowed_season_types.add("regular")
    if re.search(r"\bplay[- ]?in\b", lowered):
        allowed_season_types.add("play_in")
    if "playoff" in lowered or "postseason" in lowered:
        allowed_season_types.add("playoffs")
    if not set(plan.filters.season_types).issubset(allowed_season_types):
        return False
    # Internal entity IDs are injected only after deterministic resolution.
    return not plan.filters.player_ids and not plan.filters.game_ids


async def maybe_plan_retrieval(
    question: str,
    *,
    fallback: RetrievalPlan,
) -> RetrievalPlan:
    """Return a validated LLM retrieval plan or the deterministic fallback."""
    settings = get_settings()
    if (
        not getattr(settings, "rag_llm_planner_enabled", False)
        or settings.ai_provider.lower() in {"mock", "none", "disabled"}
        or not settings.ai_api_key
    ):
        return fallback
    if not await reserve_ai_budget(estimated_cost_usd=0.002):
        return fallback
    system = (
        "Plan retrieval for the immutable Knicks archive. Return JSON matching the "
        "provided fallback shape. Collections and fact tools are allowlisted by the "
        "schema. Set supported=true only for a historical Knicks basketball question "
        "that can be answered from this archive; set it false for software, general "
        "knowledge, live, future, injury, trade, or non-Knicks requests. Use one to "
        "three concise semantic queries. Add a team, date, period, or player filter "
        "only when explicitly present in the question. Never provide a season or data "
        "version. Do not answer the question."
    )
    try:
        raw = await get_llm_adapter(response_format_json=True).generate(
            system=system,
            user=json.dumps(
                {
                    "question": question,
                    "fallback": fallback.model_dump(mode="json"),
                },
                separators=(",", ":"),
            ),
        )
        planned = RetrievalPlan.model_validate_json(raw)
        return planned if _filters_are_grounded(planned, question) else fallback
    except Exception as exc:  # noqa: BLE001
        logger.warning("retrieval_llm_planner_failed", extra={"error_type": type(exc).__name__})
        return fallback
