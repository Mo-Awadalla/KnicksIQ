"""Player stat-threshold games through HTTP, SQL and the analyst evidence loop."""

import re
from datetime import UTC, date, datetime

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services import analyst_loop
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import SyntheticAdapter, configure, exchange
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

VERSION = "threshold-games-test"
COLUMNS = ("minutes", "points", "rebounds", "assists", "steals", "blocks", "three_pointers_made")
# (date, phase, opponent, Brunson line, Hart line); a zero-minute line is an observed DNP.
GAMES = [
    (date(2026, 1, 3), "regular", "MIA", (36, 39, 4, 10, 1, 0, 2), (30, 12, 11, 3, 1, 0, 1)),
    (date(2026, 1, 5), "regular", "DEN", (35, 40, 5, 9, 3, 1, 4), (31, 8, 9, 4, 0, 0, 0)),
    (date(2026, 1, 7), "regular", "BOS", (37, 41, 6, 11, 2, 0, 5), (29, 10, 12, 5, 2, 1, 1)),
    (date(2026, 1, 9), "regular", "PHI", (0, 0, 0, 0, 0, 0, 0), (33, 15, 8, 6, 1, 0, 2)),
    (date(2026, 2, 1), "regular", "CHA", (38, 47, 3, 7, 0, 2, 6), (28, 9, 14, 2, 0, 0, 0)),
    (date(2026, 5, 1), "playoffs", "BOS", (40, 45, 7, 8, 1, 0, 3), (35, 11, 10, 4, 1, 1, 1)),
]
DECLINE = re.compile(r"\b(can(?:'|’)?t|cannot|unable|do(?:es)? not have|not available)\b", re.I)


async def seed_threshold_release() -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        release = DatasetRelease(
            version=VERSION,
            season="2025-26",
            source="test",
            manifest_sha256="b" * 64,
            validation_passed=True,
            status="active",
            activated_at=datetime.now(UTC),
        )
        db.add(release)
        await db.flush()
        players = {
            name: (await db.execute(select(Player).where(Player.full_name == name))).scalar_one()
            for name in ("Jalen Brunson", "Josh Hart")
        }
        for index, (day, phase, opponent, brunson, hart) in enumerate(GAMES):
            game = Game(
                release_id=release.id,
                nba_game_id=f"threshold-{index}",
                season="2025-26",
                game_date=day,
                home_team_id="NYK",
                away_team_id=opponent,
                home_score=112,
                away_score=104,
                status="final",
                season_type=phase,
                source_name="test",
                source_game_id=f"threshold-{index}",
            )
            db.add(game)
            await db.flush()
            for name, line in (("Jalen Brunson", brunson), ("Josh Hart", hart)):
                db.add(
                    PlayerGameStat(
                        release_id=release.id,
                        game_id=game.id,
                        player_id=players[name].id,
                        team_id="NYK",
                        **dict(zip(COLUMNS, line, strict=True)),
                    )
                )
        await db.commit()
        return {name: player.id for name, player in players.items()}


def expected(player: str, column: str, test) -> dict[str, int]:
    """Independent oracle over observed appearances (minutes > 0), every phase."""
    index = COLUMNS.index(column)
    return {
        day.isoformat(): (brunson if player == "Jalen Brunson" else hart)[index]
        for day, _, _, brunson, hart in GAMES
        if (brunson if player == "Jalen Brunson" else hart)[0] > 0
        and test((brunson if player == "Jalen Brunson" else hart)[index])
    }


CASES = [
    (
        "Which games did Jalen Brunson score more than 40 points?",
        "Jalen Brunson",
        "points",
        ("points", ">", 40),
        lambda v: v > 40,
    ),
    (
        "In how many games did Brunson score at least 40?",
        "Jalen Brunson",
        "points",
        ("points", ">=", 40),
        lambda v: v >= 40,
    ),
    (
        "How many games did Brunson score fewer than 40 points?",
        "Jalen Brunson",
        "points",
        ("points", "<", 40),
        lambda v: v < 40,
    ),
    (
        "How many games did Josh Hart score more than 40 points?",
        "Josh Hart",
        "points",
        ("points", ">", 40),
        lambda v: v > 40,
    ),
    (
        "How many games did Brunson have at least 10 assists?",
        "Jalen Brunson",
        "assists",
        ("assists", ">=", 10),
        lambda v: v >= 10,
    ),
    (
        "How many games did Josh Hart grab more than 10 rebounds?",
        "Josh Hart",
        "rebounds",
        ("rebounds", ">", 10),
        lambda v: v > 10,
    ),
    (
        "How many games did Brunson have at least 2 steals?",
        "Jalen Brunson",
        "steals",
        ("steals", ">=", 2),
        lambda v: v >= 2,
    ),
    (
        "How many games did Brunson have more than 1 block?",
        "Jalen Brunson",
        "blocks",
        ("blocks", ">", 1),
        lambda v: v > 1,
    ),
    (
        "Which games did Brunson make at least 4 three-pointers?",
        "Jalen Brunson",
        "three_pointers_made",
        ("threes_made", ">=", 4),
        lambda v: v >= 4,
    ),
]


def verified_claims(response: dict) -> list[dict]:
    return [
        citation["metadata"]["claim"]
        for citation in response.get("citations", [])
        if citation.get("type") == "verified_claim"
    ]


@pytest.mark.parametrize("question,player,column,predicate,test", CASES)
async def test_threshold_games_are_counted_and_listed_without_a_provider(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    question,
    player,
    column,
    predicate,
    test,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)

    def denied():
        raise AssertionError("No provider is authorized for threshold regressions")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", denied)
    player_ids = await seed_threshold_release()
    payload = {"question": question, "turn_id": f"threshold-games-{abs(hash(question))}"}
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    assert response.status_code == 200
    body = response.json()
    matches = expected(player, column, test)
    appearances = expected(player, column, lambda _: True)
    claims = verified_claims(body)
    count = [c for c in claims if c["metric_id"] == "games:count"]
    assert len(count) == 1, body["answer"]
    assert count[0]["subject_id"] == f"player:{player_ids[player]}"
    assert count[0]["value"] == len(matches)
    assert count[0]["sample_size"] == len(appearances)
    stat, operator, cutoff = predicate
    assert count[0]["eligibility"]["stat_predicate"] == {
        "metric_id": stat,
        "operator": operator,
        "cutoff": cutoff,
    }
    assert str(len(matches)) in body["answer"]
    assert not DECLINE.search(body["answer"])
    if question.startswith("Which"):
        listed = {
            c["window"]["date_start"]: c["value"]
            for c in claims
            if c["metric_id"] == f"{stat}:total" and len(c["game_ids"]) == 1
        }
        assert listed == matches
    evidence = {
        item["metadata"]["date"]: item["metadata"]
        for item in capture["turn"]["committed_evidence_proposal"]["evidence"]
        if item["metadata"].get("subject_id") == f"player:{player_ids[player]}"
    }
    assert {day: evidence[day][column] for day in matches} == matches


async def test_postseason_games_are_part_of_the_default_threshold_population(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    await seed_threshold_release()
    response = await client.post(
        "/analysis/query",
        json={
            "question": "Which games did Jalen Brunson score more than 40 points?",
            "turn_id": "threshold-games-postseason",
        },
    )
    claims = verified_claims(response.json())
    phases = {
        c["window"]["date_start"]: c["season_type"] for c in claims if len(c["game_ids"]) == 1
    }
    assert phases == {"2026-01-07": "regular", "2026-02-01": "regular", "2026-05-01": "playoffs"}
    count = next(c for c in claims if c["metric_id"] == "games:count")
    assert count["season_type"] is None


async def test_unknown_player_threshold_asks_which_player(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    await seed_threshold_release()
    async with AsyncClient(
        transport=ASGITransport(client._transport.app, client=("192.0.2.77", 12345)),
        base_url="http://test",
    ) as http:
        response = await http.post(
            "/analysis/query",
            json={
                "question": "How many games did Zorp Blat score more than 30 points?",
                "turn_id": "threshold-games-unknown-player",
            },
        )
    body = response.json()
    assert body["route"] == "clarification"
    assert not verified_claims(body)
    assert "Jalen Brunson" in body["answer"] and "Josh Hart" in body["answer"]


async def test_model_receives_prepared_threshold_claims_and_cites_every_game(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    configure(monkeypatch)
    await seed_threshold_release()
    question = "Which games did Jalen Brunson score more than 40 points?"
    adapter = SyntheticAdapter({"name": "find_player_games", "question": question})
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, "threshold-games-model", question)
    assert receipt["status"] == 200
    assert receipt["response"]["llm_validated"] is True
    assert [t["call"]["name"] for t in receipt["capture"]["tools"]] == ["find_player_games"]
    claims = verified_claims(receipt["response"])
    assert next(c for c in claims if c["metric_id"] == "games:count")["value"] == 3
    assert {
        c["window"]["date_start"]: c["value"] for c in claims if c["metric_id"] == "points:total"
    } == {"2026-01-07": 41, "2026-02-01": 47, "2026-05-01": 45}
