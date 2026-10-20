"""Opponent ambiguity narrows by the question's own condition before asking, written first."""

from datetime import UTC, date, datetime

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services import analyst_loop
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from sqlalchemy import select, update

# (date, NYK home?, NYK-perspective (own, opponent) score after each scoring event).
# The last pair is the final score.
SCHEDULE = {
    "BOS": [
        # Led, then trailed, then won: a blown lead the Knicks still won.
        ("2026-01-01", True, [(2, 0), (2, 3), (8, 3)]),
        # Lost without ever leading.
        ("2026-01-02", False, [(0, 2), (0, 4), (2, 4)]),
        # Led wire to wire.
        ("2026-01-03", True, [(3, 0), (10, 0), (10, 4)]),
        # Led, then lost.
        ("2026-01-04", True, [(5, 0), (5, 7)]),
    ],
    "TOR": [
        # A strict lead loss, a trailing game tied, and a wire-to-wire win.
        ("2026-02-01", True, [(2, 0), (2, 3), (4, 3)]),
        ("2026-02-02", True, [(0, 2), (2, 2), (2, 2)]),
        ("2026-02-03", True, [(10, 0), (12, 0), (12, 4)]),
    ],
    "CHI": [
        ("2026-03-01", True, [(2, 0)]),
        ("2026-03-02", False, [(0, 3)]),
    ],
}


async def seed_schedule() -> None:
    async with AsyncSessionLocal() as db:
        release = DatasetRelease(
            version="narrowing-test",
            season="2025-26",
            source="test",
            manifest_sha256="b" * 64,
            validation_passed=True,
            status="active",
            activated_at=datetime.now(UTC),
        )
        db.add(release)
        await db.flush()
        await db.execute(
            update(DatasetRelease).where(DatasetRelease.id != release.id).values(status="retired")
        )
        for opponent, games in SCHEDULE.items():
            for day, home, timeline in games:
                own, other = timeline[-1]
                game = Game(
                    release_id=release.id,
                    nba_game_id=f"narrowing-{day}",
                    season="2025-26",
                    game_date=date.fromisoformat(day),
                    home_team_id="NYK" if home else opponent,
                    away_team_id=opponent if home else "NYK",
                    home_score=own if home else other,
                    away_score=other if home else own,
                    status="final",
                    season_type="regular",
                    source_name="test",
                    source_game_id=f"narrowing-{day}",
                )
                db.add(game)
                await db.flush()
                for sequence, (knicks, rival) in enumerate(timeline, start=1):
                    home_score, away_score = (knicks, rival) if home else (rival, knicks)
                    db.add(
                        GameEvent(
                            game_id=game.id,
                            sequence=sequence,
                            period=min(sequence, 4),
                            clock="05:00",
                            event_type="made_shot",
                            home_score=home_score,
                            away_score=away_score,
                            score_margin=home_score - away_score,
                            score_observed=True,
                        )
                    )
        await db.commit()


def configure(monkeypatch, evidence_loop: bool) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", evidence_loop)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "test_mode", False)
    monkeypatch.setattr(settings, "require_active_release", True)

    def denied():
        raise AssertionError("Narrowing must not invoke a provider")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", denied)


async def ask(client, question: str, turn: str) -> dict:
    response = await client.post(
        "/analysis/query",
        json={
            "question": question,
            "season": "2025-26",
            "turn_id": f"opponent-narrowing-{turn}",
            "expected_revision": 0,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("evidence_loop", [True, False])
@pytest.mark.parametrize(
    ("question", "listed", "excluded"),
    [
        # Blown leads count whatever the final result; a loss without a lead does not.
        (
            "How did the Knicks lose the lead against Boston?",
            ["2026-01-01", "2026-01-04"],
            ["2026-01-02", "2026-01-03"],
        ),
        ("Why did the Knicks lose to Boston?", ["2026-01-02", "2026-01-04"], ["2026-01-01"]),
        (
            "How did the Knicks erase a deficit against Toronto?",
            ["2026-02-01", "2026-02-02"],
            ["2026-02-03"],
        ),
    ],
)
async def test_several_fits_list_only_the_fitting_games(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    evidence_loop,
    question,
    listed,
    excluded,
):
    configure(monkeypatch, evidence_loop)
    monkeypatch.setattr(get_settings(), "rag_query_resolution_v2_enabled", True)
    await seed_schedule()
    body = await ask(client, question, f"several-{evidence_loop}-{len(question)}")
    assert body["route"] == "clarification"
    assert body["citations"] == []
    assert all(day in body["answer"] for day in listed), body["answer"]
    assert not any(day in body["answer"] for day in excluded), body["answer"]


@pytest.mark.parametrize(
    ("question", "chosen", "others"),
    [
        (
            "How did the Knicks lose the lead against Toronto?",
            "2026-02-01",
            ["2026-02-02", "2026-02-03"],
        ),
        ("Why did the Knicks win the Chicago game?", "2026-03-01", ["2026-03-02"]),
    ],
)
async def test_exactly_one_fit_proceeds_as_if_named(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    question,
    chosen,
    others,
):
    configure(monkeypatch, True)
    monkeypatch.setattr(get_settings(), "rag_query_resolution_v2_enabled", True)
    await seed_schedule()
    with capture_turn() as capture:
        body = await ask(client, question, f"one-{len(question)}")
    assert body["route"] != "clarification", body["answer"]
    assert "which" not in body["answer"].lower(), body["answer"]
    receipts = [e for t in capture["tools"] for e in t["result"]["evidence"]]
    assert receipts, body
    assert all(chosen in e["text"] for e in receipts), receipts


async def test_one_fit_blown_lead_evidence_survives_a_final_knicks_win(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    configure(monkeypatch, True)
    monkeypatch.setattr(get_settings(), "rag_query_resolution_v2_enabled", True)
    await seed_schedule()
    with capture_turn() as capture:
        body = await ask(
            client, "How did the Knicks lose the lead against Toronto?", "lead-evidence"
        )
    assert body["route"] != "clarification", body["answer"]
    claims = [
        item["metadata"]["claim"] for item in body["citations"] if item["type"] == "verified_claim"
    ]
    narratives = [claim for claim in claims if claim["metric_id"] == "canonical_game_narrative"]
    assert narratives, body
    narrative = narratives[0]
    assert narrative["value"]["games"][0]["date"] == "2026-02-01"
    assert [item["kind"] for item in narrative["value"]["lead_changes"]] == [
        "knicks_took_lead",
        "opponent_took_lead",
    ]
    assert [item["sequence"] for item in narrative["value"]["lead_changes"]] == [1, 2]
    assert (
        narrative["value"]["games"][0]["knicks_points"]
        > narrative["value"]["games"][0]["opponent_points"]
    )
    assert [
        (
            item["period"],
            item["sequence"],
            item["knicks_score"],
            item["opponent_score"],
        )
        for item in narrative["value"]["lead_changes"]
        if item["kind"] == "opponent_took_lead"
    ] == [(2, 2, 2, 3)]
    assert "2026-02-01" in body["answer"] and "05:00" in body["answer"]
    assert "TOR took the lead" in body["answer"]
    assert any(
        item["call"]["name"] == "get_game_narrative" and item["result"]["status"] == "ok"
        for item in capture["tools"]
    )


@pytest.mark.parametrize("evidence_loop", [True, False])
@pytest.mark.parametrize("query_resolution_v2", [False, True])
@pytest.mark.parametrize(
    ("question", "opponent", "dates"),
    [
        (
            "How did the Knicks lose the lead against Chicago?",
            ("CHI", "Chicago"),
            ("2026-03-01", "2026-03-02"),
        ),
        ("How did the Knicks lose to Toronto?", ("TOR", "Toronto"), ("2026-02-01", "2026-02-02")),
    ],
)
async def test_zero_fits_say_no_archived_game_matches(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    evidence_loop,
    question,
    opponent,
    dates,
    query_resolution_v2,
):
    configure(monkeypatch, evidence_loop)
    monkeypatch.setattr(get_settings(), "rag_query_resolution_v2_enabled", query_resolution_v2)
    await seed_schedule()
    body = await ask(client, question, f"zero-{evidence_loop}-{len(question)}")
    assert body["route"] == "clarification"
    assert body["citations"] == []
    assert "No archived" in body["answer"], body["answer"]
    assert any(name in body["answer"] for name in opponent), body["answer"]
    assert not any(day in body["answer"] for day in dates), body["answer"]


async def test_unobserved_scoreboard_scores_do_not_leak_into_lead_filter(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    configure(monkeypatch, True)
    await seed_schedule()
    async with AsyncSessionLocal() as db:
        game = (
            await db.execute(
                select(Game).where(
                    Game.game_date == date(2026, 2, 2),
                    Game.home_team_id == "NYK",
                    Game.away_team_id == "TOR",
                )
            )
        ).scalar_one()
        await db.execute(
            update(GameEvent)
            .where(GameEvent.game_id == game.id, GameEvent.sequence == 2)
            .values(home_score=0, away_score=3, score_margin=-3, score_observed=False)
        )
        await db.commit()
    with capture_turn() as capture:
        body = await ask(client, "How did the Knicks lose the lead against Toronto?", "unobserved")
    assert body["route"] != "clarification", body["answer"]
    receipts = [e for t in capture["tools"] for e in t["result"]["evidence"]]
    assert receipts, body
    assert all("2026-02-01" in e["text"] for e in receipts), receipts
    assert not any("2026-02-02" in e["text"] for e in receipts), receipts


@pytest.mark.parametrize("query_resolution_v2", [False, True])
async def test_malformed_scoreboard_does_not_fabricate_unique_lead_change(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    query_resolution_v2,
):
    configure(monkeypatch, True)
    monkeypatch.setattr(get_settings(), "rag_query_resolution_v2_enabled", query_resolution_v2)
    await seed_schedule()
    async with AsyncSessionLocal() as db:
        game = (
            await db.execute(
                select(Game).where(
                    Game.game_date == date(2026, 2, 3),
                    Game.home_team_id == "NYK",
                    Game.away_team_id == "TOR",
                )
            )
        ).scalar_one()
        await db.execute(
            update(GameEvent)
            .where(GameEvent.game_id == game.id, GameEvent.sequence == 2)
            .values(home_score=0, away_score=15, score_margin=-15, score_observed=True)
        )
        await db.commit()
    body = await ask(
        client,
        "How did the Knicks lose the lead against Toronto?",
        f"malformed-{query_resolution_v2}",
    )
    assert body["route"] == "clarification"
    assert body["citations"] == []
    assert "cannot verify" in body["answer"].lower()
    assert "2026-02-01" in body["answer"]
    assert "2026-02-03" in body["answer"]
