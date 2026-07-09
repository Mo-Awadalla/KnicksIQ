"""Tests for game endpoints."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from app.core.db import AsyncSessionLocal
from app.models.bad_stretch import BadStretch
from app.models.game import Game


async def test_root_returns_api_info(client):
    r = await client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "knicksiq-api"


async def test_health_returns_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_list_games_returns_seeded_games(client):
    r = await client.get("/games")
    assert r.status_code == 200
    games = r.json()
    assert len(games) >= 2
    for g in games:
        assert "id" in g
        assert "nba_game_id" in g
        assert "home_team_id" in g
        assert "away_team_id" in g
        assert g["margin"] == g["home_score"] - g["away_score"]
        assert g["season_type"] == "regular"
        assert g["data_status"] == "events_ready"


async def test_list_games_filter_by_season(client):
    r = await client.get("/games?season=2024-25")
    assert r.status_code == 200
    games = r.json()
    assert all(g["season"] == "2024-25" for g in games)


async def test_list_games_filter_by_team(client):
    r = await client.get("/games?team_id=NYK")
    assert r.status_code == 200
    games = r.json()
    for g in games:
        assert g["home_team_id"] == "NYK" or g["away_team_id"] == "NYK"


async def test_get_game_detail(client):
    r = await client.get("/games/1")
    assert r.status_code == 200
    game = r.json()
    assert game["id"] == 1
    assert game["home_team"] is not None
    assert game["home_team"]["abbreviation"] == "NYK"


async def test_get_game_not_found(client):
    r = await client.get("/games/9999")
    assert r.status_code == 404


async def test_get_play_by_play(client):
    r = await client.get("/games/1/play-by-play")
    assert r.status_code == 200
    events = r.json()
    assert len(events) > 0
    assert {event["period"] for event in events} == {1, 2, 3, 4}
    assert events[-1]["home_score"] == 96
    assert events[-1]["away_score"] == 110
    assert any(event["player_name"] for event in events)
    # Events should be ordered by period then sequence
    for i in range(1, len(events)):
        prev, cur = events[i - 1], events[i]
        assert (prev["period"], prev["sequence"]) <= (cur["period"], cur["sequence"])


async def test_get_play_by_play_filter_by_period(client):
    r = await client.get("/games/1/play-by-play?period=1")
    assert r.status_code == 200
    events = r.json()
    assert all(e["period"] == 1 for e in events)


async def test_summary_only_game_blocks_event_level_reads(client):
    async with AsyncSessionLocal() as session:
        session.add(
            Game(
                nba_game_id="summary-only",
                season="2025-26",
                game_date=date(2026, 4, 15),
                home_team_id="NYK",
                away_team_id="BOS",
                home_score=100,
                away_score=90,
                status="final",
                data_status="summary_only",
            )
        )
        await session.commit()

    games = (await client.get("/games?data_status=summary_only")).json()
    game_id = games[0]["id"]
    r = await client.get(f"/games/{game_id}/play-by-play")
    assert r.status_code == 409
    r = await client.get(f"/games/{game_id}/runs")
    assert r.status_code == 409


async def test_runs_endpoint_computes_from_cached_events(client):
    """Runs are computed from cached events when no persisted rows exist."""
    r = await client.get("/games/1/runs")
    assert r.status_code == 200
    assert any(run["team_id"] == "NYK" and run["score_delta"] >= 8 for run in r.json())


async def test_get_bad_stretches(client):
    async with AsyncSessionLocal() as session:
        session.add(
            BadStretch(
                game_id=1,
                period=2,
                start_clock="07:12",
                end_clock="04:58",
                score_delta=-9,
                summary="Bench unit gave up transition chances.",
                likely_causes='["turnovers", "missed shots"]',
                knicks_turnovers=3,
                knicks_missed_shots=4,
                opponent_fast_breaks=2,
            )
        )
        await session.commit()

    r = await client.get("/games/1/bad-stretches")
    assert r.status_code == 200
    assert r.json() == [
        {
            "id": 1,
            "game_id": 1,
            "period": 2,
            "start_clock": "07:12",
            "end_clock": "04:58",
            "score_delta": -9,
            "summary": "Bench unit gave up transition chances.",
            "likely_causes": ["turnovers", "missed shots"],
            "knicks_turnovers": 3,
            "knicks_missed_shots": 4,
            "opponent_fast_breaks": 2,
        }
    ]


async def test_detect_runs_endpoint_returns_202(client):
    """POST /games/{id}/detect-runs enqueues a detection job."""
    with patch("worker_app.job_queue.enqueue_detect_runs", return_value="detect123"):
        r = await client.post("/games/1/detect-runs")
    assert r.status_code == 202
    assert r.json()["job_id"] == "detect123"
    job = (await client.get("/jobs/detect123")).json()
    assert job["job_type"] == "detect_runs"
    assert job["payload"] == {"game_id": 1}
