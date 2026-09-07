"""Tests for /reports endpoints."""

from __future__ import annotations


async def test_get_report_not_found(client):
    r = await client.get("/reports/9999")
    assert r.status_code == 404


async def test_report_sources_link_the_matching_evidence_type(client, db_session):
    import json

    from app.models.game import Game
    from app.models.report import Report

    game = await db_session.get(Game, 1)
    game.nba_game_id = "0022500003"
    game.source_url = "https://stats.nba.com/stats/playbyplayv3?GameID=0022500003"
    report = Report(
        game_id=1,
        title="Verified report",
        summary="Summary",
        report_type="postgame",
        sources_json=json.dumps(
            [
                {"type": "traditional_box_score", "nba_player_id": 1628973},
                {"type": "play_by_play", "start_sequence": 10, "end_sequence": 20},
                {"type": "game"},
                "Legacy source note",
            ]
        ),
    )
    db_session.add(report)
    await db_session.commit()
    response = await client.get(f"/reports/{report.id}")
    assert response.status_code == 200
    sources = response.json()["sources"]
    assert sources[0]["source_url"].endswith("/0022500003/box-score")
    assert sources[1]["source_url"] == game.source_url
    assert sources[2]["source_url"].endswith("/0022500003/box-score")
    assert all(source["game_id"] == 1 for source in sources[:3])
    assert sources[3] == "Legacy source note"


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


async def test_report_pagination_bounds(client):
    for query in ("limit=0", "limit=201", "offset=-1"):
        response = await client.get(f"/reports?{query}")
        assert response.status_code == 422
    response = await client.get("/reports?limit=50&offset=100")
    assert response.status_code == 200
    assert response.json() == []


async def test_report_101_reachable_with_stable_tied_order(client, db_session):
    from datetime import UTC, datetime

    from app.models.report import Report

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(101):
        db_session.add(
            Report(
                game_id=1,
                title=f"Report {index}",
                summary="Summary",
                report_type="postgame",
                created_at=timestamp,
                reviewed=True,
            )
        )
    await db_session.commit()
    ids = []
    for offset, expected in [(0, 50), (50, 50), (100, 1)]:
        response = await client.get(f"/reports?limit=50&offset={offset}")
        assert response.status_code == 200
        page = response.json()
        assert len(page) == expected
        ids.extend(item["id"] for item in page)
    assert len(set(ids)) == 101
    assert ids == sorted(ids, reverse=True)
