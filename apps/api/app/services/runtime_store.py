"""Optional Redis limits and privacy-preserving response cache."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings


def answer_cache_key(question: str, data_version: str, model_version: str) -> str:
    normalized = " ".join(question.lower().split())
    payload = f"{normalized}|{data_version}|{model_version}"
    digest = hmac.new(
        get_settings().ip_hash_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"answer:{digest}"


async def _redis():
    settings = get_settings()
    if not settings.redis_url:
        return None
    from redis.asyncio import Redis

    return Redis.from_url(settings.redis_url, socket_connect_timeout=0.2, socket_timeout=0.2)


async def enforce_redis_limits(client_hash: str) -> bool:
    """Return True when Redis is degraded; raise ValueError when a limit is hit."""
    redis = await _redis()
    if redis is None:
        return True
    settings = get_settings()
    minute_key = f"limit:minute:{client_hash}"
    day_key = f"limit:day:{client_hash}"
    try:
        async with redis.pipeline(transaction=True) as pipeline:
            pipeline.incr(minute_key)
            pipeline.expire(minute_key, 60, nx=True)
            pipeline.incr(day_key)
            pipeline.expire(day_key, 86_400, nx=True)
            minute_count, _, day_count, _ = await pipeline.execute()
        if minute_count > settings.public_chat_rate_limit_per_minute:
            raise ValueError("minute")
        if day_count > settings.public_chat_rate_limit_per_day:
            raise ValueError("day")
        return False
    except ValueError:
        raise
    except Exception:  # noqa: BLE001
        return True
    finally:
        await redis.aclose()


async def get_cached_answer(key: str) -> dict[str, Any] | None:
    redis = await _redis()
    if redis is None:
        return None
    try:
        value = await redis.get(key)
        return json.loads(value) if value else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        await redis.aclose()


async def set_cached_answer(key: str, value: dict[str, Any], ttl_seconds: int = 86_400) -> None:
    redis = await _redis()
    if redis is None:
        return
    try:
        await redis.set(key, json.dumps(value, separators=(",", ":")), ex=ttl_seconds)
    except Exception:  # noqa: BLE001
        pass
    finally:
        await redis.aclose()


async def reserve_ai_budget(estimated_cost_usd: float = 0.01) -> bool:
    """Fail closed when Redis is absent or the application cutoff is reached."""
    settings = get_settings()
    if settings.test_mode:
        return True
    redis = await _redis()
    if redis is None:
        return False
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    try:
        spent = float(await redis.incrbyfloat(key, estimated_cost_usd))
        await redis.expire(key, 35 * 86_400, nx=True)
        if spent > settings.openrouter_monthly_cutoff_usd:
            await redis.incrbyfloat(key, -estimated_cost_usd)
            return False
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        await redis.aclose()
