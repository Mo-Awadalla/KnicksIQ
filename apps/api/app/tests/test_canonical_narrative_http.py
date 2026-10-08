"""Narrative policies via HTTP/SQL/Redis; synthetic CI or opt-in approved data."""

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services import analyst_loop
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

BUNDLE = Path(
    os.environ.get(
        "KNICKSIQ_APPROVED_BUNDLE",
        str(Path(__file__).with_name("fixtures") / "synthetic-archive.json.gz"),
    )
)
SHA = (
    "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"
    if os.environ.get("KNICKSIQ_APPROVED_BUNDLE")
    else "122f26722193a87349d7183ab42a479b8603c779b69f0a34bc1035356c556707"
)
CLOSEST = {"0022500372", "0022501016", "0042500122", "0042500123", "0042500402", "0042500404"}


async def request(client, redis, monkeypatch, directory, name, question, *, context=None):
    attempts = 0

    def denied():
        nonlocal attempts
        attempts += 1
        raise AssertionError("Canonical disabled-mode narratives must not construct a provider")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", denied)
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await redis.set(key, "0.125")
    payload = {
        "question": question,
        "context": context or [],
        "turn_id": f"canonical-narrative-{name}",
        "expected_revision": 0,
    }
    directory.mkdir(parents=True, exist_ok=True)
    # Independent clients preserve the normal public quota across this workload.
    ip = f"192.0.2.{len(list(directory.glob('*.json'))) + 1}"
    async with AsyncClient(
        transport=ASGITransport(client._transport.app, client=(ip, 12345)), base_url="http://test"
    ) as http:
        with capture_turn() as capture:
            response = await http.post("/analysis/query", json=payload)
        replay = await http.post("/analysis/query", json=payload)
        conflict = await http.post("/analysis/query", json={**payload, "question": "Changed input"})
    receipt = {
        "request": payload,
        "synthetic_client": ip,
        "http_status": response.status_code,
        "response": response.json(),
        "capture": capture,
        "replay": replay.json(),
        "conflict_status": conflict.status_code,
        "provider_attempts": attempts,
        "budget_before": "0.125",
        "budget_after": (await redis.get(key)).decode(),
    }
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{name}.json").open("x") as file:
        json.dump(receipt, file, indent=2)
    assert response.status_code == 200
    assert receipt["response"]["state_committed"]
    assert receipt["replay"] == receipt["response"] and conflict.status_code == 409
    assert attempts == capture["turn"]["model_calls"] == 0
    assert receipt["budget_before"] == receipt["budget_after"]
    return receipt["response"], capture


async def test_approved_archive_narratives_and_measure_clarifications(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    directory = Path(os.environ.get("KNICKSIQ_NARRATIVE_ARTIFACT_DIR", str(tmp_path)))
    record_property("narrative_artifacts", str(directory))
    cases = [
        ("closest", "Tell the story of the closest Knicks game."),
        ("closest-paraphrase", "Describe every Knicks game tied for the smallest final margin."),
        ("boston-sequence", "What was the key sequence in the Boston loss?"),
        ("boston-drought", "Which drought cost the Knicks the Boston game?"),
    ]
    for name, question in cases:
        body, capture = await request(client, local_redis, monkeypatch, directory, name, question)
        assert body["route"] != "clarification" and body["citations"]
        claims = [
            c["metadata"]["claim"] for c in body["citations"] if c["type"] == "verified_claim"
        ]
        narrative = next(c for c in claims if c["metric_id"] == "canonical_game_narrative")
        stories = narrative["value"]["games"]
        if name.startswith("closest"):
            assert {g["nba_game_id"] for g in stories} == CLOSEST
            assert len(stories) == 6
            for game in stories:
                assert game["date"] in body["answer"]
                assert abs(game["knicks_points"] - game["opponent_points"]) == 1
                assert len(game["periods"]) >= 4
        else:
            assert len(stories) == 1 and stories[0]["nba_game_id"] == "0022500320"
            runs = narrative["value"]["runs"]
            assert [(r["points"], r["start_sequence"], r["end_sequence"]) for r in runs] == [
                (12, 128, 146),
                (12, 282, 299),
            ]
            assert [[e["sequence"] for e in r["scoring_events"]] for r in runs] == [
                [128, 131, 137, 140, 144, 146],
                [282, 290, 293, 295, 299],
            ]
            for run in runs:
                assert run["start_clock"] in body["answer"] and run["end_clock"] in body["answer"]
                assert run["knicks_points"] == 0
                assert all(
                    e["canonical_id"].startswith("event:0022500320:") for e in run["scoring_events"]
                )
            assert "caused" not in body["answer"].lower()
            assert "cost the knicks" not in body["answer"].lower()
        assert any(t["call"]["name"] == "get_game_narrative" for t in capture["tools"])
    clarifications = [
        ("quarter", "Describe the Knicks' worst third quarter."),
        ("deficit", "How did the Knicks erase their largest deficit?"),
        ("opponent-run", "What was the most damaging opponent run this season?"),
        ("knics-run", "What was the Knics biggest run?"),
        ("ny-collapse", "What was NY's worst collpase?"),
    ]
    for name, question in clarifications:
        body, capture = await request(client, local_redis, monkeypatch, directory, name, question)
        assert body["route"] == "clarification" and body["citations"] == []
        assert not capture["turn"]["delivered_state"].get("claims")


async def test_unanswered_run_boundaries_and_score_corrections(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        game = (
            (
                await db.execute(
                    select(Game).where(Game.release_id == release.id).order_by(Game.game_date)
                )
            )
            .scalars()
            .first()
        )
        assert game is not None
        game.home_score, game.away_score = 1, 6
        # NYK is home. A quarter break and zero-point event preserve the first
        # Boston run; the Knicks FT separates it from the second tied maximum.
        rows = [
            (1, 1, "00:20", 0, 2),
            (2, 1, "00:00", 0, 2),
            (3, 2, "12:00", 0, 2),
            (4, 2, "11:50", 0, 3),
            (5, 2, "11:40", 1, 3),
            (6, 2, "11:30", 1, 5),
            (7, 2, "11:20", 1, 6),
        ]
        for seq, period, clock, home, away in rows:
            db.add(
                GameEvent(
                    game_id=game.id,
                    sequence=seq,
                    period=period,
                    clock=clock,
                    event_type="free_throw"
                    if seq in (4, 5, 7)
                    else "period_end"
                    if seq == 2
                    else "period_start"
                    if seq == 3
                    else "made_shot",
                    home_score=home,
                    away_score=away,
                    team_id="NYK" if seq == 5 else "BOS",
                )
            )
        await db.commit()
    directory = Path(os.environ.get("KNICKSIQ_NARRATIVE_ARTIFACT_DIR", str(tmp_path)))
    record_property("narrative_artifacts", str(directory))
    question = "Describe the largest unanswered Boston runs in the loss on 2026-01-01."
    body, _ = await request(client, local_redis, monkeypatch, directory, "boundaries", question)
    claim = next(c["metadata"]["claim"] for c in body["citations"] if c["type"] == "verified_claim")
    runs = claim["value"]["runs"]
    assert [(r["points"], r["start_sequence"], r["end_sequence"]) for r in runs] == [
        (3, 1, 4),
        (3, 6, 7),
    ]
    assert runs[0]["start_period"] == 1 and runs[0]["end_period"] == 2
    async with AsyncSessionLocal() as db:
        event = (
            await db.execute(
                select(GameEvent).where(GameEvent.game_id == game.id, GameEvent.sequence == 6)
            )
        ).scalar_one()
        event.away_score = 2
        await db.commit()
    invalid, capture = await request(
        client, local_redis, monkeypatch, directory, "score-correction", question
    )
    assert invalid["citations"] == []
    assert any(t["result"]["status"] == "incomplete_coverage" for t in capture["tools"])
    assert "verif" in invalid["answer"].lower()


async def test_all_defined_extreme_ties_ignore_nonfinal_and_foreign_games(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        games = list(
            (
                await db.execute(
                    select(Game).where(Game.release_id == release.id).order_by(Game.game_date)
                )
            ).scalars()
        )
        for index, game in enumerate(games):
            game.home_score, game.away_score = (110 if index < 2 else 101), 100
        for day in (4, 5):
            game = Game(
                nba_game_id=f"tied-win-{day}",
                season=release.season,
                release_id=release.id,
                game_date=date(2026, 1, day),
                home_team_id="NYK",
                away_team_id="BOS",
                home_score=110,
                away_score=100,
                status="final",
                season_type="regular",
            )
            db.add(game)
            games.append(game)
        db.add(
            Game(
                nba_game_id="nonfinal-outlier",
                season=release.season,
                release_id=release.id,
                game_date=date(2026, 1, 6),
                home_team_id="NYK",
                away_team_id="BOS",
                home_score=300,
                away_score=1,
                status="scheduled",
                season_type="regular",
            )
        )
        foreign = DatasetRelease(
            version="foreign-narrative",
            season=release.season,
            source="fixture",
            manifest_sha256="b" * 64,
            manifest_json="{}",
            validation_json="{}",
            validation_passed=True,
            status="staged",
        )
        db.add(foreign)
        await db.flush()
        db.add(
            Game(
                nba_game_id="foreign-outlier",
                season=release.season,
                release_id=foreign.id,
                game_date=date(2026, 1, 7),
                home_team_id="NYK",
                away_team_id="BOS",
                home_score=400,
                away_score=0,
                status="final",
                season_type="regular",
            )
        )
        await db.commit()
        winning = {g.nba_game_id for g in games if g.home_score - g.away_score == 10}
        defense = {g.nba_game_id for g in games}
    directory = Path(os.environ.get("KNICKSIQ_NARRATIVE_ARTIFACT_DIR", str(tmp_path)))
    record_property("narrative_artifacts", str(directory))
    for name, question, expected in [
        ("win-ties", "Tell the story of the biggest Knicks win.", winning),
        ("defense-ties", "Describe the best defensive game.", defense),
    ]:
        body, _ = await request(client, local_redis, monkeypatch, directory, name, question)
        assert body["route"] != "clarification" and body["citations"]
        claim = next(
            c["metadata"]["claim"] for c in body["citations"] if c["type"] == "verified_claim"
        )
        stories = claim["value"]["games"]
        assert {g["nba_game_id"] for g in stories} == expected
        assert all(g["date"] in body["answer"] for g in stories)


async def test_large_tied_selection_survives_model_text_limit(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        games = [
            Game(
                nba_game_id=f"large-tie-{i}",
                season=release.season,
                release_id=release.id,
                game_date=date(2026, 3, 1) + timedelta(days=i),
                home_team_id="NYK",
                away_team_id="BOS",
                home_score=101,
                away_score=100,
                status="final",
                season_type="regular",
            )
            for i in range(100)
        ]
        db.add_all(games)
        await db.commit()
    directory = Path(os.environ.get("KNICKSIQ_NARRATIVE_ARTIFACT_DIR", str(tmp_path)))
    record_property("narrative_artifacts", str(directory))
    body, _ = await request(
        client,
        local_redis,
        monkeypatch,
        directory,
        "large-ties",
        "Tell the story of the closest Knicks game.",
    )
    claim = next(c["metadata"]["claim"] for c in body["citations"] if c["type"] == "verified_claim")
    assert len(claim["value"]["games"]) == 100
    assert len(body["answer"]) > 6000
    assert all(str(g.game_date) in body["answer"] for g in games)


@pytest.mark.parametrize("complete", [True, False])
async def test_primary_review_requires_every_selected_game(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    complete,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "llm_primary")
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        games = list(
            (
                await db.execute(
                    select(Game).where(Game.release_id == release.id).order_by(Game.game_date)
                )
            ).scalars()
        )
        for index, game in enumerate(games):
            game.home_score, game.away_score = (110 if index < 2 else 101), 100
        await db.commit()
    calls = []

    class SyntheticAdapter:
        last_metadata = {"usage": {"cost": 0}, "provider": "synthetic"}

        async def generate(self, *, system, user):
            payload = json.loads(user)
            title = payload["schema"]["title"]
            calls.append(title)
            claim = next(
                c for c in payload["claims"] if c["metric_id"] == "canonical_game_narrative"
            )
            text = claim["statement"] if complete else "The Knicks won on 2026-01-01."
            answer = {
                "text": text,
                "claims": [{"claim_id": claim["claim_id"], "displayed_value": claim["value"]}],
                "evidence_ids": [],
                "fact_ids": [],
                "follow_up_questions": [],
            }
            if title == "Action":
                return json.dumps(
                    {"action": "answer_from_available_evidence", "tools": [], "answer": answer}
                )
            if title == "ProposedAnswer":
                return json.dumps(answer)
            return json.dumps(
                {
                    "assertions": [
                        {
                            "text": "".join(payload["review_spans"]),
                            "assertion_type": "factual",
                            "verdict": "supported",
                            "offending_text": None,
                            "supporting_claim_ids": [claim["claim_id"]],
                            "supporting_evidence_ids": [],
                            "reason": "Synthetic protocol test using exact backend statements.",
                        }
                    ],
                    "follow_up_reviews": [],
                }
            )

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: SyntheticAdapter())
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await local_redis.set(key, "0.125")
    payload = {
        "question": "Tell the story of the biggest Knicks win.",
        "turn_id": f"narrative-primary-complete-{complete}",
        "expected_revision": 0,
    }
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    replay = await client.post("/analysis/query", json=payload)
    directory = Path(os.environ.get("KNICKSIQ_NARRATIVE_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    record_property("narrative_artifacts", str(directory))
    with (directory / f"primary-complete-{complete}.json").open("x") as file:
        json.dump(
            {
                "request": payload,
                "response": response.json(),
                "replay": replay.json(),
                "capture": capture,
                "synthetic_model_schemas": calls,
                "budget_after": (await local_redis.get(key)).decode(),
                "real_provider_requests": 0,
            },
            file,
            indent=2,
        )
    body = response.json()
    assert response.status_code == 200 and body["state_committed"]
    assert body["llm_validated"] is complete
    assert "2026-01-01" in body["answer"] and "2026-01-02" in body["answer"]
    assert replay.json() == body and (await local_redis.get(key)).decode() == "0.125"
    assert ("AnswerReview" in calls) is complete
