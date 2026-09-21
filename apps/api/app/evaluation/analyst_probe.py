"""Explicit, metered capability probe; never substitutes a model or logs prompts."""

from __future__ import annotations

import asyncio
import json
import time

from app.core.config import get_settings
from app.services.analyst_budget import BudgetReservation
from app.services.evidence_contracts import (
    CONTRACT_VERSION,
    PROMPT_VERSION,
    VALIDATOR_VERSION,
    Action,
    AnswerReview,
    ProposedAnswer,
)
from app.services.report_llm import get_llm_adapter


async def probe() -> dict:
    settings = get_settings()
    results = []
    for schema, instruction in (
        (
            Action,
            "Return a call_tools action with one discover_facts tool for an interesting stat.",
        ),
        (ProposedAnswer, 'Return text "Which player?" with no claims, evidence_ids or fact_ids.'),
        (
            AnswerReview,
            'Review "Which player?" as a supported clarification, with null '
            "offending_text, no supporting references and a reason.",
        ),
    ):
        reservation = await BudgetReservation.reserve(settings.analyst_call_reservation_usd)
        if reservation is None:
            results.append(
                {"schema": schema.__name__, "passed": False, "error": "budget_unavailable"}
            )
            break
        adapter = get_llm_adapter()
        adapter.max_tokens = 1200
        if settings.analyst_provider_format == "json_schema":
            adapter.response_schema = schema.model_json_schema()
        start = time.monotonic()
        try:
            raw = await adapter.generate(
                system="Return only JSON matching the provided schema.",
                user=json.dumps({"task": instruction, "schema": schema.model_json_schema()}),
            )
            schema.model_validate_json(raw)
            results.append(
                {
                    "schema": schema.__name__,
                    "passed": True,
                    "latency_ms": round((time.monotonic() - start) * 1000),
                    "provider_metadata": adapter.last_metadata,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "schema": schema.__name__,
                    "passed": False,
                    "error": type(exc).__name__,
                    "detail": str(exc)[:500],
                }
            )
        usage = getattr(adapter, "last_metadata", {}).get("usage") or {}
        await reservation.settle(usage.get("cost"))
    return {
        "model": settings.ai_chat_model,
        "format": settings.analyst_provider_format,
        "temperature": 0,
        "schema_version": CONTRACT_VERSION,
        "prompt_version": PROMPT_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "results": results,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe()), indent=2))
