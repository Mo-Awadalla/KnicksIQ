"""Atomic reservations. A missing monthly ledger requires explicit reconciliation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.config import get_settings
from app.services.runtime_store import _redis

_RESERVE = """
local total = redis.call('GET', KEYS[1])
if not total then return 0 end
if redis.call('HEXISTS', KEYS[2], ARGV[1]) == 1 then return 0 end
if tonumber(total) + tonumber(ARGV[2]) > tonumber(ARGV[3]) then return 0 end
redis.call('INCRBYFLOAT', KEYS[1], ARGV[2])
redis.call('PERSIST', KEYS[1])
redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
return 1
"""
_SETTLE = """
local reserved = redis.call('HGET', KEYS[2], ARGV[1])
if not reserved or not redis.call('GET', KEYS[1]) then return 0 end
redis.call('INCRBYFLOAT', KEYS[1], tonumber(ARGV[2]) - tonumber(reserved))
redis.call('HDEL', KEYS[2], ARGV[1])
return 1
"""


class BudgetReservation:
    def __init__(self, key: str, identity: str, amount: float):
        self.key, self.identity, self.amount = key, identity, amount

    @classmethod
    async def reserve(cls, amount: float) -> BudgetReservation | None:
        if amount <= 0:
            raise ValueError("Reservation must be positive")
        key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
        identity = uuid.uuid4().hex
        redis = await _redis()
        if redis is None:
            return None
        try:
            accepted = await redis.eval(
                _RESERVE,
                2,
                key,
                key + ":reservations",
                identity,
                amount,
                get_settings().openrouter_monthly_cutoff_usd,
            )
            return cls(key, identity, amount) if accepted else None
        except Exception:
            return None
        finally:
            await redis.aclose()

    async def settle(self, reported_cost: float | None) -> None:
        # Unknown/timeouts remain charged, even if the HTTP request outlives its task.
        if reported_cost is None or reported_cost < 0:
            return
        redis = await _redis()
        if redis is None:
            return
        try:
            await redis.eval(
                _SETTLE, 2, self.key, self.key + ":reservations", self.identity, reported_cost
            )
        except Exception:
            pass
        finally:
            await redis.aclose()
