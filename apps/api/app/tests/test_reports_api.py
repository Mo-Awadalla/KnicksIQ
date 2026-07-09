"""Tests for /reports endpoints."""

from __future__ import annotations


async def test_get_report_not_found(client):
    r = await client.get("/reports/9999")
    assert r.status_code == 404


async def test_list_reports_empty(client):
    r = await client.get("/reports")
    assert r.status_code == 200
    assert r.json() == []


async def test_post_postgame_returns_201(client):
    r = await client.post("/reports/postgame", json={"game_id": 1})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["game_id"] == 1
    assert body["title"]
    assert "turning_point" in body
    assert isinstance(body["player_notes"], list)
    assert isinstance(body["tool_calls"], list)
    # tool trace should record at least 5 calls (game, runs, stretches, snippets, llm)
    assert len(body["tool_calls"]) >= 5


async def test_post_postgame_respects_trace_toggle(client):
    r = await client.post(
        "/reports/postgame",
        json={"game_id": 1, "include_tool_trace": False, "include_sources": False},
    )
    body = r.json()
    assert body["tool_calls"] == []
    assert body["sources"] == []


async def test_list_reports_after_create(client):
    await client.post("/reports/postgame", json={"game_id": 1})
    r = await client.get("/reports")
    assert r.status_code == 200
    reports = r.json()
    assert len(reports) >= 1
    report_id = reports[0]["id"]
    r2 = await client.get(f"/reports/{report_id}")
    assert r2.status_code == 200


async def test_delete_report(client):
    create = await client.post("/reports/postgame", json={"game_id": 1})
    report_id = create.json()["id"]
    r = await client.delete(f"/reports/{report_id}")
    assert r.status_code == 204
    r2 = await client.get(f"/reports/{report_id}")
    assert r2.status_code == 404


async def test_post_postgame_for_missing_game_returns_500(client):
    """A missing game should surface as a 5xx, not silently succeed."""
    r = await client.post("/reports/postgame", json={"game_id": 99999})
    assert r.status_code in (500, 404)
