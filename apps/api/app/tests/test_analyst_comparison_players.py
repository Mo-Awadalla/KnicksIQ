"""Appearance windows and missing groups through the public analyst endpoint."""

import pytest
from app.tests.support.analytics_workflows import ask, comparison_archive, grouped


async def test_shared_appearance_window_truncates_before_the_split(client, monkeypatch):
    version, ids = await comparison_archive(monkeypatch)
    body = await ask(
        client,
        "Compare Mikal Bridges' scoring at home and away over his last 2 appearances.",
        version,
    )
    claims = grouped(body, "points:average")
    assert set(claims) == {"home", "away"}
    assert claims["home"]["game_ids"] == [ids["2026-01-20"]]
    assert claims["away"]["game_ids"] == [ids["2026-02-20"]]
    assert claims["home"]["value"] == pytest.approx(10)
    assert claims["away"]["value"] == pytest.approx(20)
    assert claims["home"]["sample_size"] == claims["away"]["sample_size"] == 1
    assert all(claim["release_id"] == version for claim in claims.values())


async def test_shared_appearance_window_applies_before_the_opponent_split(client, monkeypatch):
    version, ids = await comparison_archive(monkeypatch)
    body = await ask(
        client,
        "Compare Mikal Bridges' scoring against Boston and Toronto over his last 3 appearances.",
        version,
    )
    claims = grouped(body, "points:average")
    assert set(claims) == {"TOR"}
    assert claims["TOR"]["game_ids"] == [ids["2025-11-10"]]
    assert claims["TOR"]["value"] == pytest.approx(10)
    assert claims["TOR"]["release_id"] == version
    assert "against bos" in body["answer"].lower() and "no observed" in body["answer"].lower()


async def test_player_group_without_observed_rows_is_reported_incomplete(client, monkeypatch):
    version, _ = await comparison_archive(monkeypatch)
    body = await ask(
        client, "Compare Donte DiVincenzo's scoring against Boston and Toronto.", version
    )
    claims = grouped(body, "points:average")
    assert set(claims) == {"BOS"}
    assert claims["BOS"]["sample_size"] == 2
    assert claims["BOS"]["release_id"] == version
    answer = body["answer"].lower()
    assert "against tor" in answer and "no observed" in answer and "does not show" in answer
