"""Tests for /jobs endpoints."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module

import pytest


@pytest.fixture
def immediate_queue(monkeypatch):
    """An external queue transport that delivers before enqueue returns."""
    from worker_app import job_queue
    from worker_app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "data_source", "static")

    class ImmediateQueue:
        def enqueue(self, target, *, kwargs, job_id):
            module, name = target.rsplit(".", 1)
            run = getattr(import_module(module), name)
            with ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(run(**kwargs))).result()

    queue = ImmediateQueue()
    monkeypatch.setattr(job_queue, "_get_queue", lambda: queue)
    return queue


async def test_get_job_not_found(client):
    response = await client.get("/jobs/nonexistent")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("url", "payload", "job_type"),
    [
        ("/jobs/ingest/games", {"season": "2025-26", "include_playoffs": True}, "ingest_games"),
        ("/jobs/ingest/game/1", None, "ingest_game_detail"),
        ("/games/1/detect-runs", None, "detect_runs"),
    ],
)
async def test_immediate_worker_completion_is_visible_from_job_status(
    client, immediate_queue, url, payload, job_type
):
    # A fast delivery must see its queued row, and publication must not overwrite completion.
    response = await client.post(url, json=payload)
    assert response.status_code == 202
    status = await client.get(f"/jobs/{response.json()['job_id']}")
    assert status.status_code == 200
    body = status.json()
    assert body["job_type"] == job_type
    assert body["status"] == "finished"
    assert body["error_message"] is None
    if payload:
        assert body["payload"] == payload


async def test_finished_job_cannot_be_restarted_or_overwritten(client, monkeypatch):
    from app.core.db import AsyncSessionLocal
    from worker_app.core.config import get_settings
    from worker_app.jobs import create_job
    from worker_app.jobs.ingest_games import ingest_games

    monkeypatch.setattr(get_settings(), "data_source", "static")
    async with AsyncSessionLocal() as db:
        await create_job(db, job_id="terminal-job", job_type="ingest_games", payload={})
    await ingest_games(job_id="terminal-job", season="2025-26")
    before = (await client.get("/jobs/terminal-job")).json()
    assert before["status"] == "finished"
    with pytest.raises(ValueError):
        await ingest_games(job_id="terminal-job", season="2025-26")
    assert (await client.get("/jobs/terminal-job")).json() == before


async def test_reingest_invalidates_analysis_derived_from_previous_events(client, monkeypatch):
    from types import SimpleNamespace

    from app.core.db import AsyncSessionLocal
    from app.models.bad_stretch import BadStretch
    from app.models.scoring_run import ScoringRun
    from worker_app.jobs import create_job
    from worker_app.jobs import ingest_game_detail as detail

    events = [
        {
            "period": 1,
            "clock": f"11:0{index}",
            "team_id": "NYK",
            "event_type": "made_shot",
            "description": "Jalen Brunson makes 2PT jumper",
            "home_score": index * 2,
            "away_score": 0,
        }
        for index in range(1, 4)
    ]
    monkeypatch.setattr(
        detail,
        "get_data_source",
        lambda *args: SimpleNamespace(
            get_game=lambda game_id: {"events": events, "source_name": "revised-feed"}
        ),
    )
    async with AsyncSessionLocal() as db:
        db.add(
            ScoringRun(
                game_id=1,
                team_id="NYK",
                period=1,
                start_sequence=1,
                end_sequence=2,
                start_clock="11:00",
                end_clock="10:00",
                points_for=10,
                points_against=0,
                score_delta=10,
                event_count=2,
                summary="Old scoring run",
            )
        )
        db.add(
            BadStretch(
                game_id=1,
                period=1,
                start_clock="11:00",
                end_clock="10:00",
                score_delta=-9,
                summary="Old turnover stretch",
                likely_causes='["turnovers"]',
            )
        )
        await db.commit()
        await create_job(db, job_id="revised-events", job_type="ingest_game_detail", payload={})
    await detail.ingest_game_detail(job_id="revised-events", game_db_id=1)
    # The revised feed has only six unanswered NYK points: neither an impactful
    # eight-point run nor an opponent bad stretch qualifies.
    assert (await client.get("/games/1/runs")).json() == []
    assert (await client.get("/games/1/bad-stretches")).json() == []
