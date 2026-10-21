"""Monthly budget ledger checks for the llm_primary preflight."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from preflight.common import Context, selected

LEDGER_CHECKS = ("ledger.present", "ledger.month", "ledger.consistent", "ledger.capacity")


def _fail_all(ctx: Context, detail: str) -> None:
    for check_id in LEDGER_CHECKS:
        if selected(ctx, check_id):
            ctx.add(check_id, False, detail, {})


async def check_ledger(ctx: Context) -> None:
    if ctx.settings is None or not ctx.settings.redis_url:
        _fail_all(ctx, "Redis URL is not configured")
        return
    from redis.asyncio import from_url

    key = ctx.args.ledger_key
    try:
        client = from_url(ctx.settings.redis_url, decode_responses=True)
    except Exception as exc:  # noqa: BLE001
        _fail_all(ctx, f"Redis client failed: {type(exc).__name__}")
        return
    try:
        raw_total = await client.get(key)
        reservations = await client.hgetall(key + ":reservations")
        ttl = await client.ttl(key)
    except Exception as exc:  # noqa: BLE001
        _fail_all(ctx, f"Redis probe failed: {type(exc).__name__}")
        return
    finally:
        await client.aclose()

    if selected(ctx, "ledger.present"):
        ctx.add(
            "ledger.present",
            raw_total is not None,
            f"{key} is present" if raw_total is not None else f"{key} is absent",
            {"key": key, "present": raw_total is not None},
        )

    expected_month = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    if selected(ctx, "ledger.month"):
        ctx.add(
            "ledger.month",
            key == expected_month,
            f"key {key}, current month {expected_month}",
            {"key": key, "expected_key": expected_month},
        )

    problems: list[str] = []
    total: float | None = None
    if raw_total is None:
        problems.append("ledger total is absent")
    else:
        try:
            total = float(raw_total)
            if not math.isfinite(total) or total < 0:
                problems.append("ledger total is not a finite non-negative number")
        except ValueError:
            problems.append("ledger total is not numeric")
    reservation_total = 0.0
    for identity, amount in reservations.items():
        try:
            value = float(amount)
        except ValueError:
            problems.append(f"reservation {identity[:8]} is not numeric")
            continue
        if not math.isfinite(value) or value <= 0:
            problems.append(f"reservation {identity[:8]} is not a positive number")
        reservation_total += value
    if total is not None and reservation_total > total + 1e-6:
        problems.append("reservations exceed the ledger total")
    if ttl != -1:
        problems.append(f"ledger TTL is {ttl}, expected -1")

    if selected(ctx, "ledger.consistent"):
        ctx.add(
            "ledger.consistent",
            not problems,
            "; ".join(problems) or "ledger total and reservations are consistent",
            {
                "key": key,
                "total_usd": total,
                "reservation_total_usd": round(reservation_total, 8),
                "reservations": len(reservations),
                "ttl_seconds": ttl,
            },
        )

    if selected(ctx, "ledger.capacity"):
        cutoff = float(ctx.settings.openrouter_monthly_cutoff_usd)
        ok = total is not None and total <= cutoff + 1e-9
        ctx.add(
            "ledger.capacity",
            ok,
            f"spend {total} of cutoff {cutoff:g} USD",
            {"total_usd": total, "cutoff_usd": cutoff},
        )


def ledger_evidence(ctx: Context) -> dict[str, Any]:
    for check in reversed(ctx.checks):
        if check.id == "ledger.consistent":
            return check.evidence
    return {}
