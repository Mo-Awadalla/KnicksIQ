"""Reconcile llm_primary monthly-ledger cost to individual provider calls.

The monthly ledger (``ai-budget:YYYY-MM``) is what the cutoff enforces. This runner sends
questions through the in-process FastAPI app, one at a time, and records for every provider
call: stage, slot reservation, reported ``usage.cost``, the amount settlement charged, token
counts including reasoning, upstream provider, finish reason and content kind.

It writes four artifacts into ``--out-dir``:

- ``calls.jsonl``: one row per provider call, in order.
- ``questions.jsonl``: one row per question with the ledger delta and reconciliation.
- ``settlements.json``: every reservation and settlement event.
- ``summary.json``: totals and the exact ledger reconciliation.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    REDIS_URL=redis://localhost:56500/14 AI_REASONING_EFFORT=none \
      uv run --package knicksiq-api python tools/release/measure_llm_cost.py \
        --questions path/to/questions.jsonl --out-dir docs/release-evidence/.../cost/prod

Read-only outside its own Redis database. It never changes the cutoff.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

import app.services.report_llm as report_llm  # noqa: E402
from app.services import analyst_budget as budget_module  # noqa: E402
from app.services.analyst_loop import AnalystLoop  # noqa: E402

CALLS: list[dict[str, Any]] = []
HTTP_BODIES: list[dict[str, Any]] = []
RESERVES: list[dict[str, Any]] = []
SETTLES: list[dict[str, Any]] = []
SETTLEMENT_GROUPS: list[dict[str, Any]] = []
_LOCK = threading.Lock()
_PROVIDER_CALLS = 0

_ORIGINAL_GENERATE = report_llm.OpenAICompatibleLLMAdapter.generate
_ORIGINAL_URLOPEN = urllib.request.urlopen
_ORIGINAL_RESERVE = budget_module.BudgetReservation.reserve.__func__
_ORIGINAL_SETTLE = budget_module.BudgetReservation.settle
_ORIGINAL_LOOP_SETTLE = AnalystLoop.settle


class _CapturedResponse:
    """Proxy that keeps the bytes the adapter reads so metadata survives errors."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.body: bytes | None = None

    def read(self, *args: Any, **kwargs: Any) -> bytes:
        data = self._response.read(*args, **kwargs)
        self.body = data
        _record_http(data, getattr(self._response, "status", None), None)
        return data

    def __enter__(self) -> _CapturedResponse:
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self._response.__exit__(*exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)


def _record_http(body: bytes | None, status: int | None, error: str | None) -> None:
    entry: dict[str, Any] = {"status": status, "error": error, "body": None}
    if body:
        try:
            entry["body"] = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            entry["body"] = body.decode("utf-8", errors="replace")[:2000]
    with _LOCK:
        HTTP_BODIES.append(entry)


def _urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        response = _ORIGINAL_URLOPEN(request, *args, **kwargs)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        _record_http(raw, exc.code, "HTTPError")
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised unchanged
        _record_http(None, None, type(exc).__name__)
        raise
    captured = _CapturedResponse(response)
    return captured


urllib.request.urlopen = _urlopen


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _http_metadata() -> dict[str, Any]:
    if not HTTP_BODIES:
        return {}
    last = HTTP_BODIES[-1]
    raw_body = last.get("body")
    metadata: dict[str, Any] = {
        "http_status": last.get("status"),
        "http_error": last.get("error"),
        "request_id": None,
        "upstream_provider": None,
        "usage_cost_usd": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "reasoning_tokens": None,
        "cached_tokens": None,
        "finish_reason": None,
        "native_finish_reason": None,
        "content_kind": None,
        "cost_details": None,
    }
    if not isinstance(raw_body, dict):
        return metadata
    body: dict[str, Any] = raw_body
    metadata["request_id"] = body.get("id")
    metadata["upstream_provider"] = body.get("provider")
    raw_usage = body.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    metadata["usage_cost_usd"] = _number(usage.get("cost"))
    metadata["prompt_tokens"] = usage.get("prompt_tokens")
    metadata["completion_tokens"] = usage.get("completion_tokens")
    metadata["total_tokens"] = usage.get("total_tokens")
    raw_details = usage.get("completion_tokens_details")
    details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
    metadata["reasoning_tokens"] = details.get("reasoning_tokens")
    raw_prompt_details = usage.get("prompt_tokens_details")
    prompt_details: dict[str, Any] = (
        raw_prompt_details if isinstance(raw_prompt_details, dict) else {}
    )
    metadata["cached_tokens"] = prompt_details.get("cached_tokens")
    metadata["cost_details"] = usage.get("cost_details")
    choices = body.get("choices")
    choice: dict[str, Any] = (
        choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    )
    metadata["finish_reason"] = choice.get("finish_reason")
    metadata["native_finish_reason"] = choice.get("native_finish_reason")
    raw_message = choice.get("message")
    message: dict[str, Any] = raw_message if isinstance(raw_message, dict) else {}
    content = message.get("content")
    metadata["content_kind"] = (
        "string"
        if isinstance(content, str) and content
        else "empty_string"
        if content == ""
        else "null"
        if content is None
        else type(content).__name__
    )
    return metadata


async def _generate(self: Any, *, system: str, user: str) -> str:
    global _PROVIDER_CALLS
    with _LOCK:
        _PROVIDER_CALLS += 1
        index = len(CALLS)
        HTTP_BODIES.clear()
        CALLS.append(
            {
                "index": index,
                "turn": None,
                "stage": None,
                "system_chars": len(system),
                "user_chars": len(user),
                "error": None,
                "error_message": None,
                "assembly_returned": False,
            }
        )
    record = CALLS[index]
    try:
        raw = await _ORIGINAL_GENERATE(self, system=system, user=user)
        record["assembly_returned"] = True
        record["raw_chars"] = len(raw)
        return raw
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised unchanged
        record["error"] = type(exc).__name__
        record["error_message"] = str(exc)[:600]
        raise
    finally:
        record.update(_http_metadata())
        record["completed_at"] = time.time()


report_llm.OpenAICompatibleLLMAdapter.generate = _generate


async def _reserve(cls: Any, amount: float) -> Any:
    reservation = await _ORIGINAL_RESERVE(cls, amount)
    RESERVES.append(
        {
            "amount": amount,
            "accepted": reservation is not None,
            "identity": reservation.identity if reservation is not None else None,
            "at": time.time(),
        }
    )
    return reservation


async def _settle(self: Any, reported_cost: float | None) -> None:
    before = await _snapshot_ledger()
    await _ORIGINAL_SETTLE(self, reported_cost)
    after = await _snapshot_ledger()
    SETTLES.append(
        {
            "identity": self.identity,
            "reserved": self.amount,
            "settled": reported_cost,
            "ledger_before": before["ledger"],
            "ledger_after": after["ledger"],
            "open_before": before["open"],
            "open_after": after["open"],
            "at": time.time(),
        }
    )


async def _loop_settle(self: AnalystLoop) -> None:
    SETTLEMENT_GROUPS.append(
        {
            "reservations": [
                {"identity": reservation.identity, "slots": slots, "amount": reservation.amount}
                for reservation, slots in self.reservations
            ],
            "costs": list(self.costs),
        }
    )
    await _ORIGINAL_LOOP_SETTLE(self)


budget_module.BudgetReservation.reserve = classmethod(_reserve)  # pyright: ignore[reportAttributeAccessIssue]
budget_module.BudgetReservation.settle = _settle
AnalystLoop.settle = _loop_settle


_LEDGER_REDIS: Any = None
_LEDGER_KEY = f"ai-budget:{datetime.now(UTC):%Y-%m}"


async def _redis_client() -> Any:
    global _LEDGER_REDIS
    if _LEDGER_REDIS is None:
        from redis.asyncio import Redis

        _LEDGER_REDIS = Redis.from_url(
            os.environ["REDIS_URL"], encoding="utf-8", decode_responses=True
        )
    return _LEDGER_REDIS


async def _snapshot_ledger() -> dict[str, Any]:
    redis = await _redis_client()
    raw = await redis.get(_LEDGER_KEY)
    reservations = await redis.hgetall(_LEDGER_KEY + ":reservations")
    return {
        "ledger": float(raw) if raw is not None else 0.0,
        "open": sum(float(value) for value in reservations.values()),
        "open_count": len(reservations),
    }


def _provider_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only request_model appends provider calls; prepare and tool stages are backend work."""
    return [entry for entry in trace if str(entry.get("tool", "")).startswith("llm_")]


async def run(cases: list[dict[str, Any]], out_dir: Path, timeout: float) -> dict[str, Any]:
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    settings = report_llm.get_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    app = create_app()
    questions: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    start_marker = len(CALLS)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", timeout=timeout
        ) as client:
            for turn_index, case in enumerate(cases):
                await asyncio.sleep(0)
                calls_before = len(CALLS)
                reserves_before = len(RESERVES)
                settles_before = len(SETTLES)
                groups_before = len(SETTLEMENT_GROUPS)
                body: dict[str, Any] = {}
                status = None
                ledger_before = await _snapshot_ledger()
                started = loop.time()
                try:
                    response = await client.post(
                        "/analysis/query",
                        json={
                            "question": case["question"],
                            "season": case.get("season", "2025-26"),
                            "turn_id": "cost-" + uuid.uuid4().hex,
                            "expected_revision": 0,
                        },
                    )
                    status = response.status_code
                    body = response.json() if status == 200 else {}
                except Exception as exc:  # noqa: BLE001 - recorded as a turn failure
                    body = {"error": f"{type(exc).__name__}: {exc}"}
                elapsed_ms = round((loop.time() - started) * 1000, 1)
                ledger_after = await _snapshot_ledger()
                cost = type(settings).model_fields.get("analyst_call_reservation_usd")
                reservation_usd = float(
                    os.environ.get("ANALYST_CALL_RESERVATION_USD")
                    or (cost.default if cost is not None else 0.01)
                )
                trace = body.get("tool_calls") or []
                provider_trace = _provider_trace(trace)
                turn_calls = CALLS[calls_before:]
                for ordinal, call in enumerate(turn_calls):
                    call["turn"] = turn_index
                    call["question_id"] = case.get("id")
                    call["ordinal"] = ordinal
                    call["stage"] = (
                        provider_trace[ordinal].get("stage")
                        if ordinal < len(provider_trace)
                        else None
                    )
                    call["reserved_usd"] = reservation_usd
                    # request_model records usage.cost only when generate returns; an
                    # exception leaves None and settlement charges the reservation.
                    call["settled_usd"] = (
                        (call.get("usage_cost_usd") or 0.0)
                        if call["assembly_returned"]
                        else reservation_usd
                    )
                turn_reserves = RESERVES[reserves_before:]
                turn_settles = SETTLES[settles_before:]
                turn_groups = SETTLEMENT_GROUPS[groups_before:]
                settled_total = sum(float(event["settled"] or 0.0) for event in turn_settles)
                ledger_delta = ledger_after["ledger"] - ledger_before["ledger"]
                open_delta = ledger_after["open"] - ledger_before["open"]
                reconciled = settled_total + open_delta
                questions.append(
                    {
                        "id": case.get("id"),
                        "category": case.get("category"),
                        "question": case["question"],
                        "status_code": status,
                        "answer": (body.get("answer") or "")[:300],
                        "llm_validated": body.get("llm_validated"),
                        "degraded": body.get("degraded"),
                        "refused": body.get("refused"),
                        "warnings": body.get("warnings") or [],
                        "provider_calls": len(turn_calls),
                        "stages": [call["stage"] for call in turn_calls],
                        "backend_trace": [entry for entry in trace if entry not in provider_trace],
                        "ledger_before": round(ledger_before["ledger"], 9),
                        "ledger_after": round(ledger_after["ledger"], 9),
                        "ledger_delta": round(ledger_delta, 9),
                        "open_before": round(ledger_before["open"], 9),
                        "open_after": round(ledger_after["open"], 9),
                        "settled_total": round(settled_total, 9),
                        "reconciled": round(reconciled, 9),
                        "reconciles": abs(ledger_delta - reconciled) < 1e-9,
                        "reservations": turn_reserves,
                        "settlements": turn_settles,
                        "settlement_groups": turn_groups,
                        "elapsed_ms": elapsed_ms,
                    }
                )
                print(
                    f"{turn_index + 1}/{len(cases)} {case.get('id')} calls={len(turn_calls)} "
                    f"delta=${ledger_delta:.6f} reconciled=${reconciled:.6f} "
                    f"ok={abs(ledger_delta - reconciled) < 1e-9}",
                    flush=True,
                )
    end_marker = len(CALLS)
    total_ledger_delta = sum(row["ledger_delta"] for row in questions)
    total_settled = sum(row["settled_total"] for row in questions)
    total_open_delta = sum(row["open_after"] - row["open_before"] for row in questions)
    calls = CALLS[start_marker:end_marker]
    summary = {
        "mode": "live in-process API",
        "settings": {
            "redis_url_db": os.environ["REDIS_URL"].rsplit("/", 1)[-1],
            "ai_provider": settings.ai_provider,
            "ai_base_url": settings.ai_base_url,
            "ai_chat_model": settings.ai_chat_model,
            "ai_reasoning_effort": settings.ai_reasoning_effort,
            "analyst_reasoning_effort": getattr(settings, "analyst_reasoning_effort", None),
            "analyst_review_max_tokens": getattr(settings, "analyst_review_max_tokens", None),
            "analyst_answer_max_tokens": getattr(settings, "analyst_answer_max_tokens", None),
            "analyst_prefetch_enabled": getattr(settings, "analyst_prefetch_enabled", None),
            "analyst_provider_format": settings.analyst_provider_format,
            "analyst_call_reservation_usd": float(
                getattr(settings, "analyst_call_reservation_usd", 0.01)
            ),
            "openrouter_monthly_cutoff_usd": settings.openrouter_monthly_cutoff_usd,
            "analyst_max_model_calls": settings.analyst_max_model_calls,
        },
        "questions": len(questions),
        "provider_calls": len(calls),
        "ledger_delta_total": round(total_ledger_delta, 9),
        "settled_total": round(total_settled, 9),
        "open_reservations_delta": round(total_open_delta, 9),
        "reconciled_total": round(total_settled + total_open_delta, 9),
        "reconciles": abs(total_ledger_delta - (total_settled + total_open_delta)) < 1e-9,
        "calls_by_stage": {},
        "calls_by_provider": {},
        "successful_calls": sum(1 for call in calls if call["assembly_returned"]),
        "failed_calls": sum(1 for call in calls if not call["assembly_returned"]),
        "reported_cost_total": round(
            sum(float(call.get("usage_cost_usd") or 0.0) for call in calls), 9
        ),
    }
    for call in calls:
        stage = call.get("stage") or "unknown"
        provider = call.get("upstream_provider") or call.get("error") or "unknown"
        summary["calls_by_stage"][stage] = summary["calls_by_stage"].get(stage, 0) + 1
        summary["calls_by_provider"][provider] = summary["calls_by_provider"].get(provider, 0) + 1
    (out_dir / "calls.jsonl").write_text(
        "".join(json.dumps(call, sort_keys=True, default=str) + "\n" for call in calls)
    )
    (out_dir / "questions.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in questions)
    )
    (out_dir / "settlements.json").write_text(
        json.dumps(
            {
                "reserves": RESERVES,
                "settles": SETTLES,
                "groups": SETTLEMENT_GROUPS,
            },
            indent=2,
            default=str,
        )
        + "\n"
    )
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.questions.read_text().splitlines() if line.strip()]
    summary = asyncio.run(run(cases, args.out_dir, args.timeout))
    if args.label:
        summary["label"] = args.label
        (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
