"""Public query scope, context, and per-client request limits."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status

from app.api.analysis_models import AnalysisContextMessage
from app.core.config import get_settings
from app.services.query_classifier import classify_query
from app.services.runtime_store import (
    enforce_redis_limits,
)
from app.services.team_aliases import team_ids_in_text

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60
_DAY_WINDOW_SECONDS = 86_400
_DEFAULT_DAY_LIMIT = 100
# One instance can only hold a bounded number of client windows in memory. Live
# windows are never evicted, because dropping one would forgive that client's accrued
# minute and day debt and hand an address-varying source a fresh budget. Capacity is
# spent at admission instead: once the table is full, an untracked identity is refused
# with the public 429 and allocates nothing, while tracked identities keep being
# charged. Expired windows are reclaimed by amortized sweeps.
_MAX_TRACKED_CLIENTS = 10_000
_PRUNE_INTERVAL_REQUESTS = 256
# A full table also sweeps on a clock, so a sustained flood cannot turn every rejected
# request into a scan of the whole identity map.
_CAPACITY_SWEEP_SECONDS = 1.0

_requests_by_client: dict[str, deque[float]] = defaultdict(deque)
_daily_requests_by_client: dict[str, deque[float]] = defaultdict(deque)
_requests_since_prune = 0
_next_capacity_sweep = 0.0


def _monotonic() -> float:
    return time.monotonic()


def reset_rate_limit_state() -> None:
    """Clear every in-process window. Used by tests and never by request handling."""
    global _requests_since_prune, _next_capacity_sweep
    _requests_by_client.clear()
    _daily_requests_by_client.clear()
    _requests_since_prune = 0
    _next_capacity_sweep = 0.0


def _trim_window(bucket: deque[float], now: float, window_seconds: float) -> None:
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()


def prune_rate_limit_state(now: float | None = None) -> int:
    """Drop identities whose minute and day windows have both expired.

    A day-rotating HMAC identity is abandoned as soon as both windows are empty, so an
    old-day key is dropped at the next sweep instead of accumulating. An identity with
    any live window is kept: its bucket holds the minute or day debt the public limits
    are enforced against, and resetting it would admit a client that has already spent
    its budget. ``_MAX_TRACKED_CLIENTS`` therefore bounds the table only because
    admission refuses untracked identities once it is reached.
    """
    moment = _monotonic() if now is None else now
    removed = 0
    for client in set(_requests_by_client) | set(_daily_requests_by_client):
        minute = _requests_by_client.get(client)
        if minute is not None:
            _trim_window(minute, moment, _WINDOW_SECONDS)
        day = _daily_requests_by_client.get(client)
        if day is not None:
            _trim_window(day, moment, _DAY_WINDOW_SECONDS)
        if not minute and not day:
            _requests_by_client.pop(client, None)
            _daily_requests_by_client.pop(client, None)
            removed += 1
    return removed


def _maybe_prune(now: float) -> None:
    global _requests_since_prune, _next_capacity_sweep
    _requests_since_prune += 1
    interval_due = _requests_since_prune >= _PRUNE_INTERVAL_REQUESTS
    capacity_due = len(_requests_by_client) >= _MAX_TRACKED_CLIENTS and now >= _next_capacity_sweep
    if not (interval_due or capacity_due):
        return
    prune_rate_limit_state(now)
    _requests_since_prune = 0
    _next_capacity_sweep = now + _CAPACITY_SWEEP_SECONDS
    if len(_requests_by_client) >= _MAX_TRACKED_CLIENTS:
        logger.warning(
            "rate limit identity table at capacity (%d); refusing new clients",
            _MAX_TRACKED_CLIENTS,
        )


def _client_id(request: Request) -> str:
    # Uvicorn resolves trusted proxy headers before constructing Request.client.
    # Never consume X-Forwarded-For directly here: a caller-controlled header
    # would let one client manufacture unlimited rate-limit identities.
    ip = request.client.host if request.client else "unknown"
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return hmac.new(
        getattr(get_settings(), "ip_hash_secret", "test-secret").encode(),
        f"{day}:{ip}".encode(),
        hashlib.sha256,
    ).hexdigest()


async def _rate_limit(request: Request) -> bool:
    settings = get_settings()
    if getattr(settings, "test_mode", False):
        return False
    client = _client_id(request)
    now = _monotonic()
    _maybe_prune(now)
    if client not in _requests_by_client and len(_requests_by_client) >= _MAX_TRACKED_CLIENTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
    bucket = _requests_by_client[client]
    _trim_window(bucket, now, _WINDOW_SECONDS)
    if len(bucket) >= settings.public_chat_rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
    bucket.append(now)
    day_bucket = _daily_requests_by_client[client]
    _trim_window(day_bucket, now, _DAY_WINDOW_SECONDS)
    if len(day_bucket) >= getattr(settings, "public_chat_rate_limit_per_day", _DEFAULT_DAY_LIMIT):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily rate limit exceeded",
        )
    day_bucket.append(now)
    try:
        return await enforce_redis_limits(client)
    except ValueError as exc:
        label = "Daily" if str(exc) == "day" else "Minute"
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"{label} rate limit exceeded",
        ) from exc


def _is_supported_question(question: str) -> bool:
    q = question.lower()
    blocked = (
        "algorithm",
        "coding",
        "compiler",
        "leetcode",
        "programming",
        "python",
        "today",
        "tonight",
        "tomorrow",
        "next game",
        "live",
        "injury",
        "trade",
        "standings",
        "yankees",
        "mets",
        "giants",
        "nets",
        "lakers",
        "warriors",
        "two sum",
    )
    if any(term in q for term in blocked):
        return False
    team_terms = (
        "knick",
        "nyk",
        "brunson",
        "towns",
        "bridges",
        "anunoby",
        "hart",
        "robinson",
        "mcbride",
        "boston",
        "celtics",
        "toronto",
        "raptors",
        "atlanta",
        "hawks",
        "chicago",
        "bulls",
        "charlotte",
        "hornets",
    )
    basketball_terms = (
        "against",
        "assist",
        "average",
        "beat",
        "bench",
        "best",
        "biggest",
        "defense",
        "deficit",
        "collapse",
        "game",
        "lineup",
        "led",
        "lead",
        "loss",
        "lose",
        "lost",
        "losing",
        "longest",
        "margin",
        "offense",
        "player",
        "perform",
        "playoff",
        "point",
        "possession",
        "receipt",
        "quarter",
        "rebound",
        "record",
        "run",
        "score",
        "season",
        "shot",
        "steal",
        "streak",
        "stretch",
        "swing",
        "turnover",
        "win",
        "worst",
        "data",
    )
    broad_archive_terms = (
        "last game",
        "4th quarter",
        "fourth quarter",
        "their biggest win",
        "their best win",
        "their biggest game",
        "their record",
        "losing streak",
        "longest streak",
        "they win",
        "they lose",
        "they lost",
        "they score",
        "who led",
        "most assists",
        "big leads",
        "comeback",
        "bench",
        "clutch",
        "shoot well",
        "from three",
        "wildest swings",
        "not in the data",
        "close games",
        "blowouts",
    )
    return (
        (any(term in q for term in team_terms) and any(term in q for term in basketball_terms))
        or (
            bool(team_ids_in_text(question))
            and bool(re.search(r"\b(?:vs|v|versus|against|do|perform)\b", q))
        )
        or (
            bool(re.search(r"\b20\d{2}-\d{2}-\d{2}\b", q))
            and (
                any(
                    term in q
                    for term in ("game", "quarter", "minute", "possession", "score", "run")
                )
                or bool(re.search(r"\bq[1-9]\b|\b(?:at|with)\s+\d{1,2}:\d{2}\b", q))
            )
        )
        or any(term in q for term in broad_archive_terms)
        or (classify_query(question).is_aggregative and any(term in q for term in basketball_terms))
    )


def _requires_explicit_refusal(question: str) -> bool:
    q = question.lower()
    return bool(
        re.search(r"\b(?:202[7-9]|20[3-9]\d)(?:-\d{2}-\d{2})?\b", q)
        or re.search(r"\b2026-(?:0[7-9]|1[0-2])-\d{2}\b", q)
        or re.search(r"\bwill\b", q)
        or any(
            term in q
            for term in (
                "today",
                "right now",
                "currently",
                "current season",
                "current stats",
                "tonight",
                "tomorrow",
                "yesterday",
                "next game",
                "upcoming",
                "live",
                "injury",
                "current injury",
                "injury status",
                "injured",
                "trade",
                "will he",
                "will they",
                "will the knicks",
                "future",
                "next season",
            )
        )
    )


def _is_greeting(question: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:hi|hello|hey|hiya|yo)(?:\s+there)?[!.?]*",
            question.strip(),
            re.IGNORECASE,
        )
    )


def _looks_like_follow_up(question: str) -> bool:
    q = question.lower().strip()
    return q.startswith(("what about", "how about", "why", "what happened then")) or q in {
        "that game",
        "those games",
        "that one",
        "tell me more",
        "explain",
        "nice",
    }


def _unknown_data_question(question: str) -> bool:
    q = question.lower()
    return "not in the data" in q or "not in knicksiq" in q


def _retrieval_limitation_note(question: str) -> str | None:
    q = question.lower()
    if _unknown_data_question(question):
        return (
            "I can only speak to the games currently in KnicksIQ. I do not have "
            "enough available season data to answer about a game outside that set."
        )
    if (
        ("who led" in q and any(term in q for term in ("scoring", "points", "assists", "rebounds")))
        or "most assists" in q
        or "most rebounds" in q
    ):
        return (
            "The available season data does not include complete player box-score "
            "leader tables for that category."
        )
    if any(term in q for term in ("bench", "defense", "rebound", "from three", "shoot well")):
        return (
            "The available season data has scores and play-by-play receipts, but not "
            "complete team/player split tables for that claim."
        )
    if any(term in q for term in ("dominated", "clutch", "blow any big leads", "big leads")):
        return (
            "The available play-by-play can show matching moments, but it is not "
            "complete enough to rank or prove that broader claim confidently."
        )
    return None


def _contextual_question(question: str, context: list[AnalysisContextMessage]) -> str:
    recent = [
        f"{item.role}: {item.content.strip()}"
        for item in context[-10:]
        if item.role in {"user", "assistant"} and item.content.strip()
    ]
    if not recent:
        return question
    return "\n".join([*recent, f"user: {question}"])
