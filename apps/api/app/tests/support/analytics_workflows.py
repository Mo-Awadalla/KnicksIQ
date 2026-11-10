"""Public analyst workflows against the comparison archive."""

from datetime import UTC, date, datetime

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.tests.test_analyst_comparisons import _seed_archive as seed_comparison
from sqlalchemy import select

ARCHIVE = (
    # date, home, away, home_score, away_score
    ("2025-11-05", "NYK", "BOS", 112, 104),
    ("2025-11-20", "BOS", "NYK", 100, 108),
    ("2025-12-05", "NYK", "BOS", 118, 110),
    ("2025-12-15", "BOS", "NYK", 120, 99),
    ("2025-12-31", "SAS", "NYK", 134, 132),
    ("2026-01-02", "NYK", "ATL", 99, 111),
    ("2026-01-03", "NYK", "PHI", 119, 130),
    ("2026-01-05", "DET", "NYK", 121, 90),
    ("2026-01-07", "NYK", "LAC", 123, 111),
    ("2026-01-14", "SAC", "NYK", 112, 101),
    ("2026-01-15", "GSW", "NYK", 126, 113),
    ("2026-01-17", "NYK", "PHX", 99, 106),
    ("2026-01-19", "NYK", "DAL", 97, 114),
    ("2026-01-21", "NYK", "BKN", 120, 66),
    ("2026-02-06", "DET", "NYK", 118, 80),
)

# Observed (home_score - away_score) values for the games with play-by-play margins.
MARGINS = {
    "2025-12-31": (4, -2),
    "2026-01-21": (0, 20, 30),
    "2026-02-06": (38, 20, 3),
}


async def seed_operations_archive(db_session) -> DatasetRelease:
    release = DatasetRelease(
        version="analyst-operations-test",
        season="2025-26",
        source="test",
        manifest_sha256="c" * 64,
        validation_passed=True,
        status="active",
        activated_at=datetime.now(UTC),
    )
    db_session.add(release)
    await db_session.flush()
    for index, (day, home, away, home_score, away_score) in enumerate(ARCHIVE):
        game = Game(
            release_id=release.id,
            nba_game_id=f"operations-{index}",
            season="2025-26",
            game_date=date.fromisoformat(day),
            home_team_id=home,
            away_team_id=away,
            home_score=home_score,
            away_score=away_score,
            status="final",
            season_type="regular",
            data_status="analysis_ready" if day in MARGINS else "summary_only",
            source_name="test",
            source_game_id=f"operations-{index}",
        )
        db_session.add(game)
        await db_session.flush()
        for sequence, margin in enumerate(MARGINS.get(day, ()), start=1):
            db_session.add(
                GameEvent(
                    game_id=game.id,
                    sequence=sequence,
                    period=1,
                    clock="12:00",
                    event_type="made_shot",
                    description="",
                    home_score=home_score,
                    away_score=away_score - margin,
                    score_margin=margin,
                )
            )
    await db_session.commit()
    return release


async def operations_archive(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "deterministic")
    async with AsyncSessionLocal() as db:
        release = await seed_operations_archive(db)
        version = release.version
        games = (
            (await db.execute(select(Game).where(Game.release_id == release.id))).scalars().all()
        )
        return version, {game.game_date.isoformat(): game.id for game in games}


async def comparison_archive(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "deterministic")
    async with AsyncSessionLocal() as db:
        release = await seed_comparison(db)
        version = release.version
        games = (
            (await db.execute(select(Game).where(Game.release_id == release.id))).scalars().all()
        )
        return version, {game.game_date.isoformat(): game.id for game in games}


async def scope_archive(monkeypatch):
    from app.tests.test_analyst_scope_composition import _seed_archive as seed_scope

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "deterministic")
    async with AsyncSessionLocal() as db:
        release = await seed_scope(db)
        version = release.version
        games = (
            (await db.execute(select(Game).where(Game.release_id == release.id))).scalars().all()
        )
        return version, {game.game_date.isoformat(): game.id for game in games}


async def player_archive(monkeypatch):
    from app.tests.support.player_archive import _seed_release_stats

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "deterministic")
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        version = release.version
        games = (
            (await db.execute(select(Game).where(Game.release_id == release.id))).scalars().all()
        )
        return version, {game.game_date.isoformat(): game.id for game in games}


async def ask(client, question, version):
    response = await client.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    body = response.json()
    assert body["data_version"] == version
    assert not body["refused"]
    return body


def delivered_claims(body):
    """Unique claim identities; one claim may cite multiple source receipts."""
    unique = {}
    for citation in body["citations"]:
        claim = citation["metadata"].get("claim")
        if claim:
            unique.setdefault(claim["claim_id"], claim)
    return list(unique.values())


def claims(body):
    delivered = delivered_claims(body)
    metrics = [claim["metric_id"] for claim in delivered]
    assert len(metrics) == len(set(metrics)), (
        f"distinct claims with duplicate metric IDs require a list: {metrics}"
    )
    return {claim["metric_id"]: claim for claim in delivered}


def grouped(body, metric):
    delivered = [claim for claim in delivered_claims(body) if claim["metric_id"] == metric]
    groups = [claim["eligibility"]["comparison_group"] for claim in delivered]
    assert len(groups) == len(set(groups)), f"duplicate comparison-group claims: {groups}"
    return dict(zip(groups, delivered, strict=True))
