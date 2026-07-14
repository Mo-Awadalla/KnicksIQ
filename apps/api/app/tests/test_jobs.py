"""Tests for /jobs endpoints."""

from __future__ import annotations

from unittest.mock import patch


async def test_get_job_not_found(client):
    r = await client.get("/jobs/nonexistent")
    assert r.status_code == 404


async def test_post_ingest_games_returns_202(client):
    """Posting ingest/games should return 202 with a job_id."""
    with patch("worker_app.job_queue.enqueue_ingest_games", return_value="abc123"):
        r = await client.post("/jobs/ingest/games", json={})
    assert r.status_code == 202
    body = r.json()
    assert body["job_id"] == "abc123"
    assert body["status"] == "queued"

    # The job should be persisted and queryable.
    r2 = await client.get("/jobs/abc123")
    assert r2.status_code == 200
    job = r2.json()
    assert job["id"] == "abc123"
    assert job["job_type"] == "ingest_games"
    assert job["status"] in ("queued", "started", "finished")


async def test_post_ingest_games_with_season(client):
    with patch("worker_app.job_queue.enqueue_ingest_games", return_value="xyz") as m:
        r = await client.post("/jobs/ingest/games", json={"season": "2024-25"})
    assert r.status_code == 202
    assert m.call_args.kwargs["season"] == "2024-25"

    job = (await client.get("/jobs/xyz")).json()
    assert job["payload"] == {"season": "2024-25"}


async def test_post_ingest_game_detail_returns_202(client):
    with patch("worker_app.job_queue.enqueue_ingest_game_detail", return_value="def") as m:
        r = await client.post("/jobs/ingest/game/1")
    assert r.status_code == 202
    assert m.call_args.kwargs["game_db_id"] == 1
    job = (await client.get("/jobs/def")).json()
    assert job["job_type"] == "ingest_game_detail"
    assert job["payload"] == {"game_id": 1}
