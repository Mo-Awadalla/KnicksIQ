"""Requested metrics, aggregate scope, all tied extrema and untrusted follow-up anchors."""

import gzip
import json
import os
from pathlib import Path

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.game import Game
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, SHA, request
from sqlalchemy import select


async def test_requested_metric_and_scope_over_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,  # noqa: F811
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = sorted(
        [g for g in raw["games"] if "NYK" in {g["home_team_id"], g["away_team_id"]}],
        key=lambda g: (g["game_date"], g["nba_game_id"]),
    )
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        ids = {g.nba_game_id: g.id for g in (await db.execute(select(Game))).scalars()}
    directory = Path(os.environ.get("KNICKSIQ_SCOPE_ARTIFACT_DIR", str(tmp_path)))
    record_property("requested_scope_artifacts", str(directory))

    def score(game):
        return (
            (game["home_score"], game["away_score"])
            if game["home_team_id"] == "NYK"
            else (game["away_score"], game["home_score"])
        )

    def record(population):
        wins = sum(score(g)[0] > score(g)[1] for g in population)
        return {"wins": wins, "losses": len(population) - wins}

    boston = [g for g in games if "BOS" in {g["home_team_id"], g["away_team_id"]}]
    home_wins = [g for g in games if g["home_team_id"] == "NYK" and score(g)[0] > score(g)[1]]
    january = [g for g in games if g["game_date"].startswith("2026-01")]
    cases = [
        (
            "total",
            "How many total points did the Knicks score?",
            games,
            {"points": sum(score(g)[0] for g in games)},
        ),
        (
            "losses",
            "How many games did the Knicks lose?",
            games,
            {"losses": record(games)["losses"]},
        ),
        (
            "home-wins",
            "How many home games did the Knicks win?",
            home_wins,
            {"wins": len(home_wins)},
        ),
        ("boston", "How did NYK do vs BOS?", boston, record(boston)),
        (
            "january",
            "How did the Knicks perform from January 1 through January 31?",
            january,
            record(january),
        ),
    ]
    failures = []
    for name, question, population, expected in cases:
        body, _ = await request(client, local_redis, monkeypatch, directory, name, question)
        claims = {
            c["metadata"]["claim"]["claim_id"]: c["metadata"]["claim"] for c in body["citations"]
        }
        if {c["metric_id"]: c["value"] for c in claims.values()} != expected or any(
            set(c["game_ids"]) != {ids[g["nba_game_id"]] for g in population}
            for c in claims.values()
        ):
            failures.append((name, "wrong requested metrics, values or population"))

    extrema = [
        (
            "biggest",
            "What was the Knicks biggest win by margin?",
            lambda g: score(g)[0] - score(g)[1],
            max,
            True,
        ),
        (
            "worst",
            "What was the Knicks worst loss by margin?",
            lambda g: score(g)[0] - score(g)[1],
            min,
            True,
        ),
        ("highest", "What was the Knicks highest-scoring game?", lambda g: score(g)[0], max, False),
        ("lowest", "What was the Knicks lowest-scoring game?", lambda g: score(g)[0], min, False),
        ("defense", "Explain the Knicks' best defensive game.", lambda g: score(g)[1], min, False),
    ]
    for name, question, value, choose, margin in extrema:
        maximum = choose(value(g) for g in games)
        population = [g for g in games if value(g) == maximum]
        body, _ = await request(client, local_redis, monkeypatch, directory, name, question)
        claims = {
            c["metadata"]["claim"]["claim_id"]: c["metadata"]["claim"] for c in body["citations"]
        }
        required = {
            (metric, ids[g["nba_game_id"]])
            for g in population
            for metric in (["game_score", "margin"] if margin else ["game_score"])
        }
        observed = {
            (c["metric_id"], c["game_ids"][0]) for c in claims.values() if len(c["game_ids"]) == 1
        }
        if required != observed:
            failures.append((name, "missing tied game or unexpected narrative metrics"))
        for claim in claims.values():
            game = next(g for g in games if ids[g["nba_game_id"]] == claim["game_ids"][0])
            opponent = (
                game["away_team_id"] if game["home_team_id"] == "NYK" else game["home_team_id"]
            )
            expected = (
                score(game)[0] - score(game)[1]
                if claim["metric_id"] == "margin"
                else {"NYK": score(game)[0], opponent: score(game)[1]}
            )
            if claim["value"] != expected:
                failures.append((name, "wrong selected game value"))

    context = [
        {"role": "user", "content": "Tell me about the Knicks Celtics game."},
        {"role": "assistant", "content": "The Knicks had a big second-half run."},
    ]
    questions = [
        "What happened next?",
        "Why was that stretch decisive?",
        "Who was on the floor then?",
        "How long did that run last?",
        "Did they recover after that?",
        "What did Brunson do during it?",
        "Show me the receipts for that.",
        "Was that their worst stretch?",
        "Compare that with the other Boston game.",
        "Compare the two Knicks games against Boston.",
    ]
    for index, question in enumerate(questions):
        body, capture = await request(
            client,
            local_redis,
            monkeypatch,
            directory,
            f"clarify-{index}",
            question,
            context=context,
        )
        if (
            body["route"] != "clarification"
            or body["citations"]
            or capture["turn"]["delivered_state"].get("claims")
        ):
            failures.append(
                (question, "unverified reference or unspecified comparison must clarify")
            )
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "summary.json").open("x") as artifact:
        json.dump(
            {
                "cases": len(cases) + len(extrema) + len(questions),
                "bundle_sha256": SHA,
                "failures": failures,
            },
            artifact,
            indent=2,
        )
    assert not failures, failures
