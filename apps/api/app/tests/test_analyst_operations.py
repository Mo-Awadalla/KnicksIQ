"""Team operations and conversation boundaries through the public analyst endpoint."""

import pytest
from app.tests.support.analytics_workflows import ask, claims, operations_archive
from app.tests.support.factual_queries import text


@pytest.mark.parametrize(
    ("question", "metric", "value", "day", "score"),
    [
        (
            "Who beat the Knicks by the most points?",
            "loss_margin",
            38,
            "2026-02-06",
            ("DET", "118", "80"),
        ),
        ("What was their best win?", "win_margin", 54, "2026-01-21", ("BKN", "120", "66")),
    ],
)
async def test_extreme_margin_names_the_correct_game(
    client, monkeypatch, question, metric, value, day, score
):
    version, ids = await operations_archive(monkeypatch)
    body = await ask(client, question, version)
    delivered = [claim.model_dump(mode="json") for claim in body.claims]
    assert len(delivered) == 1
    claim = delivered[0]
    assert claim["metric_id"] == metric
    assert claim["value"] == value
    assert claim["game_ids"] == [ids[day]]
    assert claim["release_id"] == version
    assert all(item in text(body) for item in (*score, str(value), day))


async def test_longest_losing_streak_is_broken_by_wins(client, monkeypatch):
    version, _ = await operations_archive(monkeypatch)
    body = await ask(client, "When was their longest streak of losses?", version)
    result = claims(body)
    assert result["losing_streak"]["value"] == 5
    assert result["losing_streak_length"]["value"] == 5
    assert "2025-12-15" in text(body) and "2026-01-05" in text(body)
    assert result["losing_streak"]["release_id"] == version


async def test_tied_losing_streaks_are_both_reported(client, monkeypatch):
    from app.core.db import AsyncSessionLocal
    from app.models.game import Game
    from sqlalchemy import select

    version, ids = await operations_archive(monkeypatch)
    async with AsyncSessionLocal() as db:
        game = (await db.execute(select(Game).where(Game.id == ids["2025-12-15"]))).scalar_one()
        game.away_score = 121
        await db.commit()
    body = await ask(client, "When was the longest losing streak?", version)
    streaks = [
        claim.model_dump(mode="json") for claim in body.claims if claim.metric_id == "losing_streak"
    ]
    assert len(streaks) == 2
    assert all(claim["value"] == 4 and claim["release_id"] == version for claim in streaks)
    assert "2025-12-31" in text(body) and "2026-01-14" in text(body)


async def test_requested_win_count_and_opponent_record(client, monkeypatch):
    version, _ = await operations_archive(monkeypatch)
    wins = claims(await ask(client, "How many games did the Knicks win?", version))
    assert set(wins) == {"wins"} and wins["wins"]["value"] == 5
    record = claims(await ask(client, "How did they perform against Boston?", version))
    assert set(record) == {"wins", "losses"}
    assert (record["wins"]["value"], record["losses"]["value"]) == (3, 1)
    assert all(claim["release_id"] == version for claim in record.values())


async def test_swing_ranking_limits_results_to_event_coverage(client, monkeypatch):
    version, ids = await operations_archive(monkeypatch)
    body = await ask(client, "Which games had the wildest swings?", version)
    found = [
        claim.model_dump(mode="json")
        for claim in body.claims
        if claim.metric_id == "score_margin_range"
    ]
    assert found[0]["value"] == 38
    assert {claim["game_ids"][0] for claim in found} == {
        ids[day] for day in ("2025-12-31", "2026-01-21", "2026-02-06")
    }
    assert all(claim["release_id"] == version for claim in found)
    assert "3 of 15" in text(body) or "3 of 15" in body.message


async def test_undefined_comeback_does_not_fall_back_to_totals(client, monkeypatch):
    version, _ = await operations_archive(monkeypatch)
    body = await ask(client, "What was the best comeback of the season?", version)
    assert body.status == "ambiguous_entity"
    assert not claims(body) and "won" not in text(body).lower()


async def test_ranking_and_record_followups_do_not_reuse_prior_claims(client, monkeypatch):
    from app.tests.support.analytics_workflows import query_in_release

    version, _ = await operations_archive(monkeypatch)
    state = {}
    for index, question in enumerate(
        [
            "Who beat the Knicks by the most points?",
            "What was the Knicks record this season?",
            "Who beat the Knicks by the most points?",
        ]
    ):
        body, state = await query_in_release(question, version, state)
        assert state["release"] == version
        assert "claims" not in state and "evidence" not in state
        result = claims(body)
        if index == 1:
            assert set(result) == {"wins", "losses"}
            assert (result["wins"]["value"], result["losses"]["value"]) == (5, 10)
        else:
            assert set(result) == {"loss_margin"} and result["loss_margin"]["value"] == 38
