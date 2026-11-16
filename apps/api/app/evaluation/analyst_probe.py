"""Explicit metered chat-stream capability probe. Running it spends provider budget."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Literal, NotRequired, TypedDict

import httpx

from app.conversation.provider import Completion, ProviderConfig, request_body, stream_completion
from app.core.config import get_settings
from app.services.analyst_budget import BudgetReservation


class ProbeResult(TypedDict):
    passed: bool
    error: NotRequired[str]
    delta_count: NotRequired[int]
    latency_ms: NotRequired[int]


class ProbeReport(TypedDict):
    model: str
    format: Literal["stream"]
    results: list[ProbeResult]


async def probe() -> ProbeReport:
    settings = get_settings()
    result: ProbeResult = {"passed": False}
    report: ProbeReport = {
        "model": settings.ai_chat_model,
        "format": "stream",
        "results": [result],
    }
    if (
        not settings.ai_api_key
        or settings.ai_provider.lower() in {"mock", "none", "disabled"}
        or settings.ai_chat_model not in settings.openrouter_allowed_models
    ):
        result["error"] = "provider_unavailable"
        return report
    reservation = await BudgetReservation.reserve(settings.analyst_call_reservation_usd)
    if reservation is None:
        result["error"] = "budget_unavailable"
        return report
    completion = Completion()
    config = ProviderConfig(
        settings.ai_base_url,
        settings.ai_api_key,
        settings.ai_chat_model,
        settings.ai_reasoning_effort,
        600,
    )
    started = time.monotonic()
    try:
        body = request_body(
            config,
            [{"role": "user", "content": "Say hello to a Knicks fan in one short sentence."}],
            None,
        )
        async with httpx.AsyncClient(
            timeout=settings.analyst_deadline_seconds, trust_env=False
        ) as client:
            async with asyncio.timeout(settings.analyst_deadline_seconds):
                chunks = [
                    text async for text in stream_completion(client, config, body, completion)
                ]
        result.update(
            passed=bool("".join(chunks).strip()) and completion.finish == "stop",
            delta_count=len(chunks),
            latency_ms=round((time.monotonic() - started) * 1000),
        )
    except Exception as exc:
        result["error"] = type(exc).__name__
    finally:
        await asyncio.shield(reservation.settle(completion.cost))
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe()), indent=2))
