"""In-process per-client rate-limit state stays bounded without forgiving debt.

Redis is the shared limiter when it is configured; the in-process buckets are the
single-instance fallback and must not grow without bound. Canonical identities are
day-rotating HMAC pseudonyms, so abandoned keys from earlier days have to be pruned
rather than accumulate for the life of the process.

Capacity is enforced at admission. Once the table holds the maximum number of live
identities, a client that is already tracked keeps being charged, and a client that is
not yet tracked is refused instead of allocated. Evicting a live identity would reset
its minute and day debt, which is the cheapest way for a source that can vary its
address to start over.
"""

from __future__ import annotations

import pytest
from app.api import analysis_policy as runtime
from app.core.config import get_settings
from fastapi import HTTPException, Request
from fastapi import status as http_status
from starlette.types import Scope


class _Clock:
    """Deterministic monotonic clock so window expiry is observed, not slept through."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _request(host: str | None = "203.0.113.7", **headers: str) -> Request:
    # The identity comes from the scope the server builds, so a missing peer address
    # and trusted-header resolution behave exactly as they do in production.
    scope: Scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in headers.items()
        ],
    }
    if host is not None:
        scope["client"] = (host, 0)
    return Request(scope)


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    runtime.reset_rate_limit_state()
    settings = get_settings()
    monkeypatch.setattr(settings, "test_mode", False)
    monkeypatch.setattr(settings, "public_chat_rate_limit_per_minute", 3)
    monkeypatch.setattr(settings, "public_chat_rate_limit_per_day", 5)

    async def _healthy(_client: str) -> bool:
        return False

    monkeypatch.setattr(runtime, "enforce_redis_limits", _healthy)
    yield
    runtime.reset_rate_limit_state()


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    tick = _Clock()
    monkeypatch.setattr(runtime, "_monotonic", tick)
    return tick


async def test_abandoned_old_day_identities_are_pruned(clock):
    for octet in range(1, 41):
        await runtime._rate_limit(_request(host=f"198.51.100.{octet}"))
    assert len(runtime._requests_by_client) == 40

    removed = runtime.prune_rate_limit_state(now=clock.now + 86_401)

    assert removed == 40
    assert runtime._requests_by_client == {}
    assert runtime._daily_requests_by_client == {}


async def test_capacity_sheds_new_identities_and_keeps_existing_enforcement(monkeypatch, clock):
    monkeypatch.setattr(runtime, "_MAX_TRACKED_CLIENTS", 2)
    redis_calls: list[str] = []

    async def _counted(client: str) -> bool:
        redis_calls.append(client)
        return False

    monkeypatch.setattr(runtime, "enforce_redis_limits", _counted)
    resident = _request(host="198.51.100.1")
    neighbour = _request(host="198.51.100.2")
    for request in (resident, neighbour):
        for _ in range(3):
            assert await runtime._rate_limit(request) is False
    tracked = set(runtime._requests_by_client)
    assert len(tracked) == 2

    # The tracked client keeps its accrued minute debt at capacity.
    with pytest.raises(HTTPException) as excinfo:
        await runtime._rate_limit(resident)
    assert excinfo.value.status_code == http_status.HTTP_429_TOO_MANY_REQUESTS

    newcomer = _request(host="198.51.100.3")
    newcomer_id = runtime._client_id(newcomer)
    calls_before = len(redis_calls)
    with pytest.raises(HTTPException) as excinfo:
        await runtime._rate_limit(newcomer)
    assert excinfo.value.status_code == http_status.HTTP_429_TOO_MANY_REQUESTS
    assert excinfo.value.detail == "Rate limit exceeded"

    # The shed client allocated nothing and consumed no shared quota.
    assert set(runtime._requests_by_client) == tracked
    assert newcomer_id not in runtime._requests_by_client
    assert newcomer_id not in runtime._daily_requests_by_client
    assert len(redis_calls) == calls_before


async def test_capacity_pressure_does_not_rescan_per_request(monkeypatch, clock):
    monkeypatch.setattr(runtime, "_MAX_TRACKED_CLIENTS", 4)
    sweeps: list[float] = []
    original = runtime.prune_rate_limit_state

    def _counted(now=None):
        sweeps.append(clock.now if now is None else now)
        return original(now)

    monkeypatch.setattr(runtime, "prune_rate_limit_state", _counted)
    for index in range(1, 21):
        try:
            await runtime._rate_limit(_request(host=f"198.51.100.{index}"))
        except HTTPException:
            pass

    assert len(sweeps) <= 2


async def test_capacity_pressure_preserves_day_debt(monkeypatch, clock):
    monkeypatch.setattr(runtime, "_MAX_TRACKED_CLIENTS", 2)
    resident = _request(host="198.51.100.1")
    for _ in range(3):
        assert await runtime._rate_limit(resident) is False
    assert await runtime._rate_limit(_request(host="198.51.100.2")) is False

    clock.advance(61)
    with pytest.raises(HTTPException):
        await runtime._rate_limit(_request(host="198.51.100.3"))

    # The minute window expired, but the three day-window requests still count.
    assert await runtime._rate_limit(resident) is False
    assert await runtime._rate_limit(resident) is False
    with pytest.raises(HTTPException) as excinfo:
        await runtime._rate_limit(resident)
    assert excinfo.value.detail == "Daily rate limit exceeded"


async def test_admission_resumes_after_windows_expire(monkeypatch, clock):
    monkeypatch.setattr(runtime, "_MAX_TRACKED_CLIENTS", 2)
    for host in ("198.51.100.1", "198.51.100.2"):
        assert await runtime._rate_limit(_request(host=host)) is False

    saturated = _request(host="198.51.100.3")
    with pytest.raises(HTTPException):
        await runtime._rate_limit(saturated)

    clock.advance(86_401)

    assert await runtime._rate_limit(saturated) is False
    assert runtime._client_id(saturated) in runtime._requests_by_client


async def test_pruning_never_refills_an_active_window(clock):
    for _ in range(2):
        await runtime._rate_limit(_request())

    runtime.prune_rate_limit_state(now=clock.now + 30)

    assert await runtime._rate_limit(_request()) is False
    with pytest.raises(HTTPException):
        await runtime._rate_limit(_request())


async def test_redis_day_rejection_maps_to_the_public_envelope(monkeypatch, clock):
    async def _reject(_client: str) -> bool:
        raise ValueError("day")

    monkeypatch.setattr(runtime, "enforce_redis_limits", _reject)
    with pytest.raises(HTTPException) as excinfo:
        await runtime._rate_limit(_request())
    assert excinfo.value.status_code == http_status.HTTP_429_TOO_MANY_REQUESTS
    assert excinfo.value.detail == "Daily rate limit exceeded"


async def test_redis_outage_degrades_instead_of_blocking(monkeypatch, clock):
    async def _degraded(_client: str) -> bool:
        return True

    monkeypatch.setattr(runtime, "enforce_redis_limits", _degraded)
    assert await runtime._rate_limit(_request()) is True


async def test_forwarded_header_cannot_mint_a_new_identity(monkeypatch, clock):
    monkeypatch.setattr(runtime, "_MAX_TRACKED_CLIENTS", 10_000)
    for _ in range(3):
        await runtime._rate_limit(_request())

    with pytest.raises(HTTPException):
        await runtime._rate_limit(
            _request(**{"x-forwarded-for": "198.51.100.99", "x-real-ip": "198.51.100.98"})
        )
    assert len(runtime._requests_by_client) == 1


async def test_identity_is_a_day_scoped_pseudonym(clock):
    client_id = runtime._client_id(_request())
    assert len(client_id) == 64
    assert "203.0.113.7" not in client_id
    assert client_id == runtime._client_id(_request())


async def test_missing_connection_address_shares_one_bucket(clock):
    await runtime._rate_limit(_request(host=None))
    assert len(runtime._requests_by_client) == 1
