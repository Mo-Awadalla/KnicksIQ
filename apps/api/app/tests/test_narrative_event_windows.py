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
from app.services.analyst_tools import AnalystTools
from app.tests.support.factual_queries import lookup, text
from app.tests.support.narrative_seed import active_seed_release as active_seed_release
from sqlalchemy import event, select


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
    body = await query(payload)
    assert body.status not in {"ok", "incomplete_coverage"}
    assert body.evidence == []
    assert "Brunson made 2pt jumper" not in text(body)


async def test_ambiguous_biggest_run_requires_clarification(active_seed_release):
    body = await query(
        {"question": "What was the biggest run in the fourth quarter on 2026-04-12?"}
    )
    assert body.status == "ambiguous_entity"
    assert body.evidence == []


async def test_first_quarter_only_cites_active_first_period(staged_window):
    body = await query({"question": "What happened in Q1 on 2026-04-12?"})
    assert body.status in {"ok", "incomplete_coverage"}
    assert body.scope["release"] == "narrative-seed-test"
    assert body.evidence
    assert {citation.game_id for citation in body.evidence} == {1}
    rows = [row for citation in body.evidence for row in citation.metadata.get("rows", [])]
    assert rows
    assert all(row["period"] == 1 for row in rows)
    assert any(
        row["clock"] == "11:36" and row["home_score"] == 2 and row["away_score"] == 0
        for row in rows
    )
    assert "Staged-only event" not in text(body)
    assert all(row["description"] != "Staged-only event" for row in rows)


async def test_exact_clock_cites_only_the_requested_instant(staged_window):
    body = await query({"question": "What happened at 11:36 in Q1 on 2026-04-12?"})
    assert body.status in {"ok", "incomplete_coverage"}
    rows = [row for citation in body.evidence for row in citation.metadata.get("rows", [])]
    assert rows
    assert all(row["period"] == 1 and row["clock"] == "11:36" for row in rows)
    assert all(row["description"] != "Staged-only event" for row in rows)


async def test_clock_without_period_requires_clarification(active_seed_release):
    body = await query({"question": "What happened at 11:36 on 2026-04-12?"})
    assert body.status == "ambiguous_entity"
    assert body.evidence == []


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
    body = await query({"question": question})
    assert body.status == "ambiguous_entity"
    assert body.evidence == []


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
    body = await query({"question": question})
    assert body.status in {"ok", "incomplete_coverage"}
    rows = [row for citation in body.evidence for row in citation.metadata.get("rows", [])]
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
        body = await query({"question": "What happened in Q1 on 2026-04-12?"})
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail_event_query)
    assert attempted
    assert body.status == "dependency_failure"
    assert body.evidence == []
    assert "96" not in text(body) and "110" not in text(body)


async def query(payload):
    async with AsyncSessionLocal() as db:
        release = (
            await db.execute(
                select(DatasetRelease).where(
                    DatasetRelease.status == "active", DatasetRelease.validation_passed.is_(True)
                )
            )
        ).scalar_one()
        tools = AnalystTools(
            db, release, payload["question"], payload.get("season", release.season), {}
        )
        await tools.prepare()
        return await lookup(tools)
