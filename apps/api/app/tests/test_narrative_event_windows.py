"""Public event-window regressions.

Failures covered: a foreign request or question season leaking active-release events;
ambiguous run metrics being answered as ordinary quarter narratives; quarter spellings
selecting the wrong periods; an unqualified clock silently choosing a period; a staged
release contaminating an active window; and an event-query failure becoming an HTTP
500 or an unsupported whole-game answer.
"""

from __future__ import annotations

from datetime import date

import pytest
from app.core.db import AsyncSessionLocal, engine
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.tests.analysis_test_support import active_seed_release as active_seed_release
from app.tests.analysis_test_support import isolate_response_cache as isolate_response_cache
from sqlalchemy import event


@pytest.fixture
async def staged_window(active_seed_release):
    async with AsyncSessionLocal() as db:
        staged = DatasetRelease(
            version="event-window-staged",
            season="2025-26",
            source="test",
            manifest_sha256="b" * 64,
            validation_passed=True,
            status="staged",
        )
        db.add(staged)
        await db.flush()
        game = Game(
            release_id=staged.id,
            nba_game_id="staged-window-game",
            season="2025-26",
            game_date=date(2026, 4, 12),
            home_team_id="NYK",
            away_team_id="CHA",
            home_score=199,
            away_score=50,
            status="final",
            season_type="regular",
        )
        db.add(game)
        await db.flush()
        db.add(
            GameEvent(
                game_id=game.id,
                sequence=1,
                period=1,
                clock="11:36",
                event_type="made_shot",
                description="Staged-only event",
                home_score=199,
                away_score=50,
            )
        )
        await db.commit()
    return active_seed_release


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "What happened in Q1 on 2026-04-12?", "season": "2024-25"},
        {"question": "What happened in Q1 on 2026-04-12 in the 2024-25 season?"},
    ],
)
async def test_foreign_season_never_returns_active_events(active_seed_release, payload):
    response = await active_seed_release.post("/analysis/query", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] != "answer"
    assert body["citations"] == []
    assert "Brunson made 2pt jumper" not in body["answer"]


async def test_ambiguous_biggest_run_requires_clarification(active_seed_release):
    response = await active_seed_release.post(
        "/analysis/query",
        json={"question": "What was the biggest run in the fourth quarter on 2026-04-12?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "clarify"
    assert body["citations"] == []


async def test_first_quarter_only_cites_active_first_period(staged_window):
    response = await staged_window.post(
        "/analysis/query", json={"question": "What happened in Q1 on 2026-04-12?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answer"
    assert body["data_version"] == "narrative-seed-test"
    assert body["citations"]
    assert {citation["game_id"] for citation in body["citations"]} == {1}
    rows = [row for citation in body["citations"] for row in citation["metadata"].get("rows", [])]
    assert rows
    assert all(row["period"] == 1 for row in rows)
    assert any(
        row["clock"] == "11:36" and row["home_score"] == 2 and row["away_score"] == 0
        for row in rows
    )
    assert "Staged-only event" not in body["answer"]
    assert all(row["description"] != "Staged-only event" for row in rows)


async def test_exact_clock_cites_only_the_requested_instant(staged_window):
    response = await staged_window.post(
        "/analysis/query",
        json={"question": "What happened at 11:36 in Q1 on 2026-04-12?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answer"
    rows = [row for citation in body["citations"] for row in citation["metadata"].get("rows", [])]
    assert rows
    assert all(row["period"] == 1 and row["clock"] == "11:36" for row in rows)
    assert all(row["description"] != "Staged-only event" for row in rows)


async def test_clock_without_period_requires_clarification(active_seed_release):
    response = await active_seed_release.post(
        "/analysis/query", json={"question": "What happened at 11:36 on 2026-04-12?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "clarify"
    assert body["citations"] == []


@pytest.mark.parametrize(
    "question",
    [
        "What happened at 12:01 in Q1 on 2026-04-12?",
        "What happened at 5:01 in Q5 on 2026-04-12?",
        "What happened at 1:99 in Q1 on 2026-04-12?",
        "What happened at 0:00.5 in Q1 on 2026-04-12?",
        "What happened at 11:36 and at 9:30 in Q1 on 2026-04-12?",
    ],
)
async def test_invalid_or_conflicting_clocks_require_clarification(active_seed_release, question):
    response = await active_seed_release.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "clarify"
    assert body["citations"] == []


@pytest.mark.parametrize(("period", "clock"), [(1, "12:00"), (5, "5:00")])
async def test_period_start_clock_returns_matching_event(active_seed_release, period, clock):
    async with AsyncSessionLocal() as db:
        db.add(
            GameEvent(
                game_id=1,
                sequence=1000 + period,
                period=period,
                clock=clock,
                event_type="period_start",
                description=f"Boundary start Q{period}",
            )
        )
        await db.commit()
    question = f"What happened at {clock} in Q{period} on 2026-04-12?"
    response = await active_seed_release.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answer"
    rows = [row for citation in body["citations"] for row in citation["metadata"].get("rows", [])]
    assert rows
    assert all(row["period"] == period and row["clock"] == clock for row in rows)
    assert any(row["description"] == f"Boundary start Q{period}" for row in rows)


async def test_event_query_failure_degrades_without_whole_game_answer(active_seed_release):
    attempted = False

    def fail_event_query(_connection, _cursor, _statement, _parameters, context, _executemany):
        nonlocal attempted
        compiled = context.compiled
        statement = compiled.statement if compiled is not None else None
        descriptions = getattr(statement, "column_descriptions", ())
        if any(description.get("entity") is GameEvent for description in descriptions):
            attempted = True
            raise RuntimeError("event database unavailable")

    event.listen(engine.sync_engine, "before_cursor_execute", fail_event_query)
    try:
        response = await active_seed_release.post(
            "/analysis/query", json={"question": "What happened in Q1 on 2026-04-12?"}
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail_event_query)
    assert attempted
    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert body["citations"] == []
    assert "96" not in body["answer"] and "110" not in body["answer"]
