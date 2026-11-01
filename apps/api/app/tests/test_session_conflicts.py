"""Public session conflict codes and boundary revision normalization."""

from __future__ import annotations

import pytest
from app.core.config import get_settings
from app.services.analyst_sessions import SessionConflict, SessionTurn
from app.tests.support.analyst_protocol import (
    local_redis as local_redis,
)
from app.tests.support.player_archive import _seed_release_stats


async def test_boundary_normalizes_numeric_revision_to_revision_conflict(local_redis):
    first = await SessionTurn.begin(None, "revision-turn-a", 0, {"question": "stat"})
    assert await first.commit({"answer": "Committed"}, {})
    with pytest.raises(SessionConflict) as stale:
        await SessionTurn.begin(first.token, "revision-turn-b", 0, {"question": "stat"})
    assert stale.value.reason == "revision_conflict"
    assert stale.value.current_revision == 1
    await local_redis.delete(first.key)


async def test_boundary_distinguishes_reuse_progress_and_expiry(local_redis):
    first = await SessionTurn.begin(None, "shape-turn-a", 0, {"question": "stat"})
    assert await first.commit({"answer": "Committed"}, {})
    active = await SessionTurn.begin(first.token, "shape-turn-b", 1, {"question": "stat"})
    with pytest.raises(SessionConflict) as busy:
        await SessionTurn.begin(first.token, "shape-turn-c", 1, {"question": "stat"})
    assert busy.value.reason == "turn_in_progress"
    assert busy.value.current_revision is None
    await active.abort()
    with pytest.raises(SessionConflict) as reused:
        await SessionTurn.begin(first.token, "shape-turn-a", 1, {"question": "changed"})
    assert reused.value.reason == "turn_id_reused"
    assert reused.value.current_revision is None
    await local_redis.delete(first.key)
    with pytest.raises(SessionConflict) as expired:
        await SessionTurn.begin(first.token, "shape-turn-c", 1, {"question": "stat"})
    assert expired.value.reason == "session_expired"
    assert expired.value.current_revision is None


async def test_route_emits_typed_conflict_envelope(client, local_redis, monkeypatch):
    from app.core.db import AsyncSessionLocal

    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", True)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    request = {
        "question": "Brunson regular season points",
        "turn_id": "envelope-turn-0001",
        "expected_revision": 0,
    }
    first = await client.post("/analysis/query", json=request)
    assert first.status_code == 200
    token = first.json()["session_token"]
    assert token and len(token) == 64

    stale = await client.post(
        "/analysis/query",
        json={
            "question": "Brunson regular season points",
            "turn_id": "envelope-turn-0002",
            "session_token": token,
            "expected_revision": 0,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"
    assert stale.json()["error"]["current_revision"] == 1
    assert token not in stale.text

    reused = await client.post(
        "/analysis/query",
        json={
            "question": "A different question",
            "turn_id": "envelope-turn-0001",
            "session_token": token,
            "expected_revision": 1,
        },
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "turn_id_reused"

    await local_redis.delete(f"analyst:{{{token}}}")
    expired = await client.post(
        "/analysis/query",
        json={
            "question": "Brunson regular season points",
            "turn_id": "envelope-turn-0003",
            "session_token": token,
            "expected_revision": 1,
        },
    )
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "session_expired"
    assert token not in expired.text
