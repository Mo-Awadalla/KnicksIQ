"""Launch query scope and conversation referents through real HTTP, SQL, and Redis."""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.models.player import Player
from app.services import analyst_loop
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats
from sqlalchemy import select


def message(content, role="user"):
    return {"role": role, "content": content}


async def seed_scope_cases():
    async with AsyncSessionLocal() as db:
        release, brunson = await _seed_release_stats(db)
        names = ("Karl-Anthony Towns", "Josh Hart", "Mikal Bridges")
        players = {
            name: (await db.execute(select(Player).where(Player.full_name == name))).scalar_one()
            for name in names
        }

        async def add_game(key, day, opponent, phase, rows, *, win=True):
            game = Game(
                release_id=release.id,
                nba_game_id=key,
                season="2025-26",
                game_date=day,
                home_team_id="NYK",
                away_team_id=opponent,
                home_score=115 if win else 90,
                away_score=105 if win else 100,
                status="final",
                season_type=phase,
                source_name="test",
                source_game_id=key,
            )
            db.add(game)
            await db.flush()
            for player, points, rebounds in rows:
                db.add(
                    PlayerGameStat(
                        release_id=release.id,
                        game_id=game.id,
                        player_id=player.id,
                        team_id="NYK",
                        minutes=30,
                        points=points,
                        rebounds=rebounds,
                        field_goals_attempted=10,
                    )
                )
            return game.id

        christmas = await add_game(
            "scope-christmas",
            date(2025, 12, 25),
            "GSW",
            "regular",
            [(brunson, 34, 4), (players["Karl-Anthony Towns"], 20, 12)],
        )
        matching = []
        for index, day in enumerate((10, 12, 14)):
            matching.append(
                await add_game(
                    f"scope-threshold-{index}",
                    date(2026, 1, day),
                    ("BOS", "MIA", "ORL")[index],
                    "regular",
                    [
                        (brunson, 41, 4),
                        (players["Karl-Anthony Towns"], 20, 8),
                        (players["Josh Hart"], 12, 7),
                    ],
                    win=index < 2,
                )
            )
        denver = await add_game(
            "scope-denver",
            date(2026, 2, 4),
            "DEN",
            "regular",
            [
                (brunson, 28, 5),
                (players["Karl-Anthony Towns"], 18, 12),
                (players["Josh Hart"], 8, 10),
            ],
        )
        spurs = []
        for index, points in enumerate((11, 10, 12, 9, 10)):
            spurs.append(
                await add_game(
                    f"scope-spurs-{index}",
                    date(2026, 5, index + 1),
                    "SAS",
                    "playoffs",
                    [
                        (players["Mikal Bridges"], points, 5),
                        (players["Karl-Anthony Towns"], 10, 8),
                    ],
                )
            )
        await db.commit()
        return {"christmas": christmas, "matching": matching, "denver": denver, "spurs": spurs}


def disable_provider(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "analysis_shadow_sample_rate", 0)

    def denied():
        raise AssertionError("The deterministic HTTP regression must not invoke a provider")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", denied)


def verified_claims(body):
    return [
        item["metadata"]["claim"]
        for item in body["citations"]
        if item["type"] == "verified_claim"
    ]


def save_receipt(tmp_path, record_property, name, value):
    directory = Path(os.environ.get("KNICKSIQ_CONTEXT_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    with path.open("x") as artifact:
        json.dump(value, artifact, indent=2)
    record_property("fan_scope_artifact", str(path))


async def test_per_game_rate_uses_all_playoff_appearances(
    client, local_redis, monkeypatch, tmp_path, record_property
):
    disable_provider(monkeypatch)
    ids = await seed_scope_cases()
    payload = {
        "question": "How many points per game did Mikal Bridges score against the Spurs in the playoffs?",
        "season": "2025-26",
        "turn_id": "scope-rate-http-20261020",
        "expected_revision": 0,
    }
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    body = response.json()
    save_receipt(
        tmp_path, record_property, "per-game-rate", {"request": payload, "response": body, "capture": capture}
    )
    scope = capture["turn"]["committed_evidence_proposal"]["scope"]
    assert response.status_code == 200 and body["route"] != "clarification"
    average = next(claim for claim in verified_claims(body) if claim["metric_id"] == "points:average")
    assert scope["opponent_id"] == "SAS" and scope["season_type"] == "playoffs"
    assert set(scope["game_ids"]) == set(ids["spurs"])
    assert average["value"] == pytest.approx(10.4)
    assert average["sample_size"] == 5 and set(average["game_ids"]) == set(ids["spurs"])


async def test_christmas_day_is_scoped_to_active_season_date(
    client, local_redis, monkeypatch, tmp_path, record_property
):
    disable_provider(monkeypatch)
    ids = await seed_scope_cases()
    payload = {
        "question": "Who led the Knicks in scoring on Christmas Day?",
        "season": "2025-26",
        "turn_id": "scope-christmas-http-20261020",
        "expected_revision": 0,
    }
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    body = response.json()
    save_receipt(
        tmp_path, record_property, "christmas-day", {"request": payload, "response": body, "capture": capture}
    )
    scope = capture["turn"]["committed_evidence_proposal"]["scope"]
    leaders = [claim for claim in verified_claims(body) if claim["metric_id"] == "points:leaders"]
    assert response.status_code == 200 and leaders
    assert scope["date_start"] == scope["date_end"] == "2025-12-25"
    assert leaders[0]["game_ids"] == [ids["christmas"]]
    assert "Jalen Brunson" in leaders[0]["statement"] and "34" in leaders[0]["statement"]


async def test_all_of_those_games_uses_delivered_matches_without_win_prefilter(
    client, local_redis, monkeypatch, tmp_path, record_property
):
    disable_provider(monkeypatch)
    ids = await seed_scope_cases()
    setup = "How many games did Jalen Brunson score more than 40 points in?"
    first_payload = {
        "question": setup,
        "season": "2025-26",
        "turn_id": "scope-threshold-first-20261020",
        "expected_revision": 0,
    }
    first = await client.post("/analysis/query", json=first_payload)
    initial = first.json()
    count = next(claim for claim in verified_claims(initial) if claim["metric_id"] == "games:count")
    assert set(count["game_ids"]) == set(ids["matching"])
    assert set(count["eligibility"]["matching_game_ids"]) == set(ids["matching"])
    payload = {
        "question": "Did the Knicks win all of those games?",
        "context": [message(setup), message(initial["answer"], "assistant")],
        "turn_id": "scope-threshold-followup-20261020",
        "session_token": initial["session_token"],
        "expected_revision": initial["revision"],
    }
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    body = response.json()
    save_receipt(
        tmp_path,
        record_property,
        "threshold-followup",
        {"first_request": first_payload, "first": initial, "request": payload, "response": body, "capture": capture},
    )
    scope = capture["turn"]["committed_evidence_proposal"]["scope"]
    values = {claim["metric_id"]: claim["value"] for claim in verified_claims(body)}
    assert first.status_code == response.status_code == 200
    assert set(scope["game_ids"]) == set(ids["matching"]) and len(scope["game_ids"]) == 3
    assert scope["game_result"] is None
    assert values["wins"] == 2 and values["losses"] == 1


async def test_that_night_reuses_recent_game_identity_and_recomputes_leader(
    client, local_redis, monkeypatch, tmp_path, record_property
):
    disable_provider(monkeypatch)
    ids = await seed_scope_cases()
    setup = "How did Jalen Brunson play against Denver on February 4?"
    first_payload = {"question": setup, "season": "2025-26", "turn_id": "scope-denver-first"}
    with capture_turn() as first_capture:
        first = await client.post("/analysis/query", json=first_payload)
    initial = first.json()
    first_scope = first_capture["turn"]["committed_evidence_proposal"]["scope"]
    assert first.status_code == 200
    assert first_scope["player_ids"] and first_scope["game_ids"] == [ids["denver"]]
    payload = {
        "question": "Who led the Knicks in rebounds that night?",
        "context": [message(setup), message(initial["answer"], "assistant")],
        "turn_id": "scope-denver-followup",
        "session_token": initial["session_token"],
        "expected_revision": initial["revision"],
    }
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    body = response.json()
    save_receipt(
        tmp_path,
        record_property,
        "that-night",
        {
            "first_request": first_payload,
            "first": initial,
            "first_capture": first_capture,
            "request": payload,
            "response": body,
            "capture": capture,
        },
    )
    scope = capture["turn"]["committed_evidence_proposal"]["scope"]
    leaders = [claim for claim in verified_claims(body) if claim["metric_id"] == "rebounds:leaders"]
    assert first.status_code == response.status_code == 200 and leaders
    assert scope["game_ids"] == [ids["denver"]]
    assert scope["player_ids"] == []
    assert leaders[0]["game_ids"] == [ids["denver"]]
    assert "Karl-Anthony Towns" in leaders[0]["statement"] and "12" in leaders[0]["statement"]


async def test_release_mismatch_requires_fresh_game_identity(
    client, local_redis, monkeypatch, tmp_path, record_property
):
    disable_provider(monkeypatch)
    await seed_scope_cases()
    first_payload = {
        "question": "How many points did JB score on 2026-01-03?",
        "turn_id": "scope-release-first",
        "expected_revision": 0,
    }
    first = await client.post("/analysis/query", json=first_payload)
    initial = first.json()
    session_key = f"analyst:{{{initial['session_token']}}}"
    raw_state = await local_redis.hget(session_key, "state")
    assert raw_state
    state = json.loads(raw_state)
    state["release"] = "retired-release"
    state["scope"]["data_version"] = "retired-release"
    await local_redis.hset(session_key, "state", json.dumps(state))
    payload = {
        "question": "How did JB play in that game?",
        "context": [message("The Boston game on 2026-01-03.")],
        "turn_id": "scope-release-followup",
        "session_token": initial["session_token"],
        "expected_revision": initial["revision"],
    }
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    body = response.json()
    save_receipt(
        tmp_path,
        record_property,
        "release-mismatch",
        {
            "first_request": first_payload,
            "first": initial,
            "request": payload,
            "response": body,
            "capture": capture,
        },
    )
    assert first.status_code == response.status_code == 200
    assert body["route"] == "clarification" and body["citations"] == []
    assert capture["turn"]["model_calls"] == 0

async def test_date_with_multiple_game_identities_still_clarifies(
    client, local_redis, monkeypatch, tmp_path, record_property
):
    disable_provider(monkeypatch)
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        db.add(
            Game(
                release_id=release.id,
                nba_game_id="scope-duplicate-date",
                season="2025-26",
                game_date=date(2026, 1, 3),
                home_team_id="NYK",
                away_team_id="DEN",
                home_score=110,
                away_score=100,
                status="final",
                season_type="regular",
                source_name="test",
                source_game_id="scope-duplicate-date",
            )
        )
        await db.commit()
    payload = {
        "question": "Who led the Knicks in rebounds that night?",
        "context": [message("The Knicks played on January 3, 2026.")],
        "season": "2025-26",
        "turn_id": "scope-duplicate-date-http",
        "expected_revision": 0,
    }
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    body = response.json()
    save_receipt(
        tmp_path, record_property, "duplicate-date", {"request": payload, "response": body, "capture": capture}
    )
    assert response.status_code == 200 and body["route"] == "clarification"
    assert body["citations"] == [] and capture["turn"]["model_calls"] == 0
