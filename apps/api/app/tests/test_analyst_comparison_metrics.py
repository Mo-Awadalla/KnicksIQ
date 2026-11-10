"""Requested comparison metrics through the public analyst endpoint."""

import pytest
from app.tests.support.analytics_workflows import ask, comparison_archive, grouped


async def test_defense_comparison_reports_points_allowed(client, monkeypatch):
    version, ids = await comparison_archive(monkeypatch)
    body = await ask(client, "Compare the Knicks' defense at home and on the road.", version)
    claims = grouped(body, "points_allowed_per_game")
    assert set(claims) == {"home", "away"}
    assert claims["home"]["value"] == pytest.approx(102.6)
    assert claims["away"]["value"] == pytest.approx(93)
    assert claims["home"]["game_ids"] == sorted(
        ids[d] for d in ("2025-11-01", "2025-11-10", "2025-11-15", "2026-01-20", "2026-06-10")
    )
    assert claims["away"]["game_ids"] == sorted(
        ids[d] for d in ("2025-11-05", "2026-02-10", "2026-02-20")
    )
    assert all(claim["release_id"] == version for claim in claims.values())


async def test_total_request_keeps_a_total_points_fact(client, monkeypatch):
    version, _ = await comparison_archive(monkeypatch)
    body = await ask(client, "Compare the Knicks' total points at home and on the road.", version)
    claims = grouped(body, "points")
    assert set(claims) == {"home", "away"}
    assert (claims["home"]["value"], claims["away"]["value"]) == (544, 308)
    assert claims["home"]["denominator"] is None
    assert (claims["home"]["sample_size"], claims["away"]["sample_size"]) == (5, 3)
