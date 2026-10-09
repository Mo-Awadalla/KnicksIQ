"""Atomic reservations. A missing monthly ledger requires explicit reconciliation."""

from __future__ import annotations

import math
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
_RETAIN = """
local raw_total = redis.call('GET', KEYS[1])
local raw_reserved = redis.call('HGET', KEYS[2], ARGV[1])
if not raw_total or not raw_reserved then return nil end
if redis.call('TTL', KEYS[1]) ~= -1 or redis.call('TTL', KEYS[2]) ~= -1 then
  return nil
end
local total = tonumber(raw_total)
local reserved = tonumber(raw_reserved)
local actual = tonumber(ARGV[2])
local function finite_nonnegative(value)
  return value and value == value and value >= 0 and value < math.huge
end
if not finite_nonnegative(total) or not finite_nonnegative(reserved)
   or not finite_nonnegative(actual) or reserved <= 0 or reserved > total then return nil end
if actual > reserved then
  redis.call('INCRBYFLOAT', KEYS[1], actual - reserved)
  redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
end
return redis.call('HGET', KEYS[2], ARGV[1])
"""


def valid_reported_cost(value: object) -> bool:
    """Provider costs must be actual finite numbers, never coerced strings/bools."""
    if not isinstance(value, (int, float)) or type(value) not in {int, float}:
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


class BudgetReservation:
    def __init__(self, key: str, identity: str, amount: float):
        self.key, self.identity, self.amount = key, identity, amount

    @classmethod
    async def reserve(cls, amount: float) -> BudgetReservation | None:
        if not valid_reported_cost(amount) or amount <= 0:
            raise ValueError("Reservation must be finite and positive")
        cutoff = get_settings().openrouter_monthly_cutoff_usd
        if not valid_reported_cost(cutoff) or cutoff <= 0:
            raise ValueError("Monthly cutoff must be finite and positive")
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
                cutoff,
            )
            return cls(key, identity, amount) if accepted else None
        except Exception:
            return None
        finally:
            await redis.aclose()

    async def retain_at_least(self, amount: float) -> float:
        """Monotonically charge known exposure while retaining uncertainty.

        This is accounting for an already transmitted request, NOT admission or
        an increased allowance. It preserves the original month and ticket, and
        never releases a reservation or initializes/repairs missing accounting.
        The caller must stop further transmissions after an over-bound receipt.
        """
        if type(amount) not in {int, float} or not math.isfinite(amount) or amount < 0:
            raise ValueError("Retained exposure must be finite and nonnegative")
        if not math.isfinite(self.amount) or self.amount <= 0:
            raise ValueError("Original retained reservation is malformed")
        redis = await _redis()
        if redis is None:
            raise ValueError("Monthly accounting unavailable for retained exposure")
        try:
            raw = await redis.eval(
                _RETAIN, 2, self.key, self.key + ":reservations", self.identity, amount
            )
            if raw is None:
                raise ValueError("Missing, malformed, or expiring retained accounting")
            retained = float(raw)
            if not math.isfinite(retained) or retained < max(self.amount, amount):
                raise ValueError("Retained accounting did not preserve known exposure")
            self.amount = retained
            return retained
        finally:
            await redis.aclose()

    async def settle(self, reported_cost: float | None) -> None:
        # Unknown/timeouts remain charged, even if the HTTP request outlives its task.
        if reported_cost is None or not valid_reported_cost(reported_cost):
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
