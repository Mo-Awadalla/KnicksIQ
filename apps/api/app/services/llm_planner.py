"""Optional LLM planner for low-confidence routing fallback."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.services.query_classifier import QueryClassifierResult
from app.services.report_llm import get_llm_adapter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlannerResult:
    intent: str
    confidence: float
    route: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "planner_confidence": self.confidence,
            "planner_route": self.route,
            "planner_used": True,
        }


async def maybe_plan_query(
    question: str,
    classifier: QueryClassifierResult,
) -> PlannerResult | None:
    settings = get_settings()
    if not settings.rag_llm_planner_enabled:
        return None
    if classifier.confidence >= settings.rag_planner_confidence_threshold:
        return None
    if settings.ai_provider.lower() in {"mock", "none", "disabled"} or not settings.ai_api_key:
        return None

    system = (
        "Classify this Knicks cached-season question. Return compact JSON with "
        "intent, route, confidence. route must be table_rag or retrieval_rag."
    )
    try:
        raw = await get_llm_adapter(response_format_json=True).generate(
            system=system,
            user=json.dumps({"question": question, "classifier": classifier.as_dict()}),
        )
        parsed = json.loads(raw)
        route = parsed.get("route")
        if route not in {"table_rag", "retrieval_rag"}:
            return None
        return PlannerResult(
            intent=str(parsed.get("intent") or classifier.kind),
            confidence=float(parsed.get("confidence") or 0.0),
            route=route,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_planner_failed", exc_info=exc)
        return None
