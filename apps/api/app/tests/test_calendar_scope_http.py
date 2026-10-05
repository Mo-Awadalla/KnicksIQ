"""Calendar scopes and missing definitions through real HTTP, SQL, and Redis."""

import gzip
import json
import os
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.game import Game
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, SHA, request
from sqlalchemy import select


async def archive(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    source = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = sorted(
        [g for g in source["games"] if "NYK" in {g["home_team_id"], g["away_team_id"]}],
        key=lambda g: (g["game_date"], g["nba_game_id"]),
    )
    async with AsyncSessionLocal() as db:
        release = await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        rows = list(
            (await db.execute(select(Game).where(Game.release_id == release.release_id))).scalars()
        )
        sql_ids = {g.nba_game_id: g.id for g in rows}
    return source, games, sql_ids


def points(game):
    return (
        (game["home_score"], game["away_score"])
        if game["home_team_id"] == "NYK"
        else (game["away_score"], game["home_score"])
    )


def artifact_directory(tmp_path, record_property, name):
    directory = Path(os.environ.get("KNICKSIQ_CALENDAR_ARTIFACT_DIR", str(tmp_path))) / name
    record_property("calendar_artifacts", str(directory))
    return directory


@pytest.mark.parametrize(
    "name,question,start,end,metric",
    [
        (
            "january-range",
            "What was the Knicks record from January 10 through January 20?",
            "2026-01-10",
            "2026-01-20",
            "wins",
        ),
        (
            "february-range",
            "How many points did the Knicks average from February 1 through February 10?",
            "2026-02-01",
            "2026-02-10",
            "points:average",
        ),
        (
            "january-between",
            "What was their record between January 10 and January 20?",
            "2026-01-10",
            "2026-01-20",
            "wins",
        ),
        (
            "original-january",
            "How did the Knicks perform from January 1 through January 31?",
            "2026-01-01",
            "2026-01-31",
            "wins",
        ),
        (
            "original-march",
            "How many games did they play between March 1 and March 15?",
            "2026-03-01",
            "2026-03-15",
            "games:count",
        ),
        (
            "explicit-iso",
            "What was their record from 2026-01-10 through 2026-01-20?",
            "2026-01-10",
            "2026-01-20",
            "wins",
        ),
        (
            "explicit-named",
            "What was their record from January 10, 2026 through January 20, 2026?",
            "2026-01-10",
            "2026-01-20",
            "wins",
        ),
        (
            "cross-year",
            "What was their record from December 20 through January 10?",
            "2025-12-20",
            "2026-01-10",
            "wins",
        ),
        (
            "all-star",
            "What was their record after the All-Star break?",
            "2026-02-16",
            "2026-12-31",
            "wins",
        ),
    ],
)
async def test_calendar_ranges_use_active_season(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,
    start,
    end,
    metric,  # noqa: F811
):
    _, games, sql_ids = await archive(monkeypatch)
    population = [g for g in games if start <= g["game_date"] <= end]
    assert population, "The portable archive must exercise each requested range."
    own = sum(points(g)[0] for g in population)
    wins = sum(points(g)[0] > points(g)[1] for g in population)
    value = (
        own / len(population)
        if metric == "points:average"
        else len(population)
        if metric == "games:count"
        else wins
    )
    expected = {
        "date_start": start,
        "date_end": end,
        "metric": metric,
        "value": value,
        "games": sorted(g["nba_game_id"] for g in population),
        "sample_size": len(population),
    }
    directory = artifact_directory(tmp_path, record_property, name)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "expected.json").open("x") as artifact:
        json.dump(expected, artifact, indent=2)
    body, _ = await request(client, local_redis, monkeypatch, directory, name, question)
    assert body["route"] != "clarification", body["answer"]
    claims = [c["metadata"]["claim"] for c in body["citations"] if c["type"] == "verified_claim"]
    claim = next(c for c in claims if c["metric_id"] == metric)
    assert claim["value"] == pytest.approx(value)
    assert claim["sample_size"] == len(population)
    assert set(claim["game_ids"]) == {sql_ids[g["nba_game_id"]] for g in population}
    if metric == "wins":
        losses = next(c for c in claims if c["metric_id"] == "losses")
        assert losses["value"] == len(population) - wins
        assert set(losses["game_ids"]) == set(claim["game_ids"])


@pytest.mark.parametrize(
    "name,question",
    [
        ("back-to-back", "How many back-to-backs did they win in February?"),
        ("back-to-back-paraphrase", "What was their record in back to back games?"),
        ("offense-defense", "Which was stronger: the Knicks offense or defense?"),
        ("offense-defense-paraphrase", "Compare New York's offense versus defense."),
        ("boston-offense", "Compare the Celtics offense with the Knicks offense."),
        ("league", "Compare the Knicks with the league."),
        ("close-blowouts", "Compare close games with blowouts."),
        ("invalid-date", "What was their record from February 30 through March 2?"),
    ],
)
async def test_missing_calendar_and_comparison_definitions_clarify(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,  # noqa: F811
):
    await archive(monkeypatch)
    directory = artifact_directory(tmp_path, record_property, name)
    body, _ = await request(client, local_redis, monkeypatch, directory, name, question)
    assert body["route"] == "clarification" and body["citations"] == [], body["answer"]


async def test_unsupported_explicit_year_never_falls_back_to_active_totals(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,  # noqa: F811
):
    await archive(monkeypatch)
    directory = artifact_directory(tmp_path, record_property, "unsupported-year")
    body, _ = await request(
        client,
        local_redis,
        monkeypatch,
        directory,
        "unsupported-year",
        "What was the Knicks record from January 10, 2024 through January 20, 2024?",
    )
    assert body["citations"] == [], body["answer"]
