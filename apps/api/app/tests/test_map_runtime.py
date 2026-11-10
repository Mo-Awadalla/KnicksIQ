"""Read-only bundle-to-SQL verification: positive and tampered restore cases.

These cases were authored before ``tools/release/runtime_mapping.py`` existed. Each one
builds a real (SQLite) database from a synthetic approved bundle, then proves the
verifier either generates the recorded mapping or fails closed on a missing, extra,
duplicate, relabelled or value-changed row. Nothing here contacts PostgreSQL, a
provider or a remote host, and no case writes to the database.
"""

from __future__ import annotations

import gzip
import hashlib
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from app.models import Base
from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
from app.models.team import Team
from app.services.release_bundle import canonical_json
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

REPO = Path(__file__).resolve().parents[4]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.release.runtime_mapping import (  # noqa: E402
    VerificationError,
    build_mapping_payload,
    digest,
    loopback_dsn,
    main,
    verify_restore,
)

VERSION = "2025-26.20260928.1"

GAME_FIELDS: dict[str, Any] = {
    "away_score": 111,
    "away_team_id": "BOS",
    "data_status": "analysis_ready",
    "game_date": "2025-10-22",
    "game_label": None,
    "home_score": 119,
    "home_team_id": "NYK",
    "nba_game_id": "0022500003",
    "season": "2025-26",
    "season_type": "regular",
    "series_game_number": None,
    "series_name": None,
    # SQLite cannot retain a UTC offset on a naive round trip; the Postgres run
    # verifies the offset-bearing value the approved bundle actually carries.
    "source_fetched_at": "2026-07-02T17:34:48.243949",
    "source_game_id": "0022500003",
    "source_name": "NbaApiDataSource",
    "source_payload_hash": "1d0190811246218c975f0d38c29e533504888475e6fd25349d48b8723eb88b8d",
    "source_url": "https://stats.nba.com/stats/playbyplayv3?GameID=0022500003",
    "status": "final",
}

PLAYER_STAT_FIELDS: dict[str, Any] = {
    "assists": 2,
    "blocks": 1,
    "defensive_rebounds": 12,
    "field_goals_attempted": 17,
    "field_goals_made": 9,
    "free_throws_attempted": 4,
    "free_throws_made": 2,
    "minutes": 37.5,
    "nba_game_id": "0022500003",
    "nba_player_id": 1628384,
    "offensive_rebounds": 2,
    "personal_fouls": 0,
    "plus_minus": 10,
    "points": 24,
    "position": "F",
    "rebounds": 14,
    "starter": True,
    "steals": 3,
    "team_id": "NYK",
    "three_pointers_attempted": 9,
    "three_pointers_made": 4,
    "turnovers": 4,
}

TEAM_STAT_FIELDS: dict[str, Any] = {
    "assists": 22,
    "blocks": 4,
    "defensive_rebounds": 39,
    "field_goals_attempted": 86,
    "field_goals_made": 37,
    "free_throws_attempted": 36,
    "free_throws_made": 31,
    "nba_game_id": "0022500003",
    "offensive_rebounds": 9,
    "personal_fouls": 23,
    "plus_minus": 8,
    "points": 119,
    "rebounds": 48,
    "steals": 8,
    "team_id": "NYK",
    "three_pointers_attempted": 40,
    "three_pointers_made": 14,
    "turnovers": 13,
}

PERIOD_FIELDS: dict[str, Any] = {
    "nba_game_id": "0022500003",
    "period": 1,
    "points": 33,
    "team_id": "NYK",
}


def _second(values: dict[str, Any], **updates: Any) -> dict[str, Any]:
    row = dict(values)
    row.update(updates)
    return row


def _bundle() -> dict[str, Any]:
    games = [
        dict(GAME_FIELDS),
        _second(
            GAME_FIELDS,
            nba_game_id="0022500018",
            game_date="2025-10-24",
            home_team_id="BOS",
            away_team_id="NYK",
            home_score=100,
            away_score=108,
            source_game_id="0022500018",
        ),
    ]
    player_stats = [
        dict(PLAYER_STAT_FIELDS),
        _second(PLAYER_STAT_FIELDS, nba_game_id="0022500018"),
        _second(PLAYER_STAT_FIELDS, nba_player_id=1626157, points=10, minutes=28.0),
    ]
    team_stats = [
        dict(TEAM_STAT_FIELDS),
        _second(TEAM_STAT_FIELDS, nba_game_id="0022500018", points=108),
    ]
    periods = [
        dict(PERIOD_FIELDS),
        _second(PERIOD_FIELDS, nba_game_id="0022500018", points=30),
    ]
    events = [
        {
            "nba_game_id": GAME_FIELDS["nba_game_id"],
            "sequence": 1,
            "period": 1,
            "clock": "11:36",
            "nba_player_id": 1628384,
            "team_id": "NYK",
            "event_type": "made_shot",
            "description": "Jalen Brunson made 2pt jumper",
            "home_score": 2,
            "away_score": 0,
            "score_margin": 2,
            "shot_type": "2pt",
            "shot_result": "made",
            "shot_distance_ft": 8,
        }
    ]
    return {
        "games": games,
        "player_game_stats": player_stats,
        "team_game_stats": team_stats,
        "period_scores": periods,
        "events": events,
        "players": [
            {"nba_player_id": 1628384, "full_name": "Jalen Brunson"},
            {"nba_player_id": 1626157, "full_name": "Karl-Anthony Towns"},
        ],
        "teams": [
            {
                "id": "NYK",
                "nba_team_id": 1610612752,
                "name": "Knicks",
                "city": "New York",
                "abbreviation": "NYK",
            },
            {
                "id": "BOS",
                "nba_team_id": 1610612738,
                "name": "Celtics",
                "city": "Boston",
                "abbreviation": "BOS",
            },
        ],
    }


def _write_bundle(path: Path, content: dict[str, Any]) -> str:
    manifest = {
        "version": VERSION,
        "season": "2025-26",
        "source": "test",
        "content_sha256": hashlib.sha256(canonical_json(content)).hexdigest(),
    }
    raw = canonical_json({"manifest": manifest, "data": content})
    path.write_bytes(gzip.compress(raw, mtime=0))
    return hashlib.sha256(path.read_bytes()).hexdigest()


TABLES = [
    Base.metadata.tables[model.__tablename__]
    for model in (
        DatasetRelease,
        Team,
        Player,
        Game,
        GameEvent,
        PlayerGameStat,
        TeamGameStat,
        PeriodScore,
    )
]


async def _seed(path: Path, *, bundle_sha256: str) -> tuple[Any, Any]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=TABLES))
    session = async_sessionmaker(engine, expire_on_commit=False)
    content = _bundle()
    async with session() as db:
        release = DatasetRelease(
            version=VERSION,
            season="2025-26",
            source="test",
            manifest_sha256=bundle_sha256,
            validation_passed=True,
            status="active",
        )
        db.add(release)
        for row in content["teams"]:
            db.add(Team(**row))
        await db.flush()
        for row in content["players"]:
            db.add(Player(**row, team_id="NYK"))
        await db.flush()
        players = {
            player.nba_player_id: player for player in (await db.execute(select(Player))).scalars()
        }
        games: dict[str, Game] = {}
        for raw in content["games"]:
            row = dict(raw)
            row["game_date"] = date.fromisoformat(row["game_date"])
            row["source_fetched_at"] = datetime.fromisoformat(row["source_fetched_at"])
            row["release_id"] = release.id
            game = Game(**row)
            db.add(game)
            games[game.nba_game_id] = game
            await db.flush()
        for raw in content["events"]:
            db.add(
                GameEvent(
                    game_id=games[raw["nba_game_id"]].id,
                    player_id=players[raw["nba_player_id"]].id,
                    **{
                        key: value
                        for key, value in raw.items()
                        if key not in {"nba_game_id", "nba_player_id"}
                    },
                )
            )

        for raw in content["player_game_stats"]:
            row = {
                key: value
                for key, value in raw.items()
                if key not in {"nba_game_id", "nba_player_id"}
            }
            db.add(
                PlayerGameStat(
                    game_id=games[raw["nba_game_id"]].id,
                    release_id=release.id,
                    player_id=players[raw["nba_player_id"]].id,
                    **row,
                )
            )
        for raw in content["team_game_stats"]:
            row = {key: value for key, value in raw.items() if key != "nba_game_id"}
            db.add(TeamGameStat(game_id=games[raw["nba_game_id"]].id, release_id=release.id, **row))
        for raw in content["period_scores"]:
            row = {key: value for key, value in raw.items() if key != "nba_game_id"}
            db.add(PeriodScore(game_id=games[raw["nba_game_id"]].id, release_id=release.id, **row))
        await db.commit()
    return engine, session


@pytest.fixture
async def restore(tmp_path: Path):
    content = _bundle()
    bundle_path = tmp_path / "bundle.json.gz"
    sha = _write_bundle(bundle_path, content)
    engine, session = await _seed(tmp_path / "restore.sqlite", bundle_sha256=sha)
    yield {
        "bundle_path": bundle_path,
        "bundle": {"data": content, "bundle_sha256": sha},
        "sha": sha,
        "engine": engine,
        "session": session,
        "database": tmp_path / "restore.sqlite",
    }
    await engine.dispose()


async def test_verified_restore_generates_the_recorded_mapping(restore) -> None:
    async with restore["session"]() as db:
        result = await verify_restore(db, restore["bundle"])
    assert result.problems == ()
    payload = build_mapping_payload(result, restore["bundle"])
    assert payload["version"] == VERSION
    assert payload["release_id"] == 1
    assert payload["bundle_sha256"] == restore["sha"]
    game = payload["rows"]["game:0022500003"]
    assert game["collection"] == "games"
    assert game["row_sha256"] == digest(GAME_FIELDS)
    assert game["runtime_receipt"] == f"{VERSION}:game:{game['game_id']}"
    box = payload["rows"]["box:0022500003:1628384"]
    assert box["collection"] == "player_game_stats"
    assert box["row_sha256"] == digest(PLAYER_STAT_FIELDS)
    assert box["player_id"] > 0
    assert box["runtime_receipt"] == f"{VERSION}:game:{box['game_id']}:player:{box['player_id']}"
    assert payload["rows"]["team_box:0022500003:NYK"]["row_sha256"] == digest(TEAM_STAT_FIELDS)
    assert payload["rows"]["period:0022500003:NYK:1"]["row_sha256"] == digest(PERIOD_FIELDS)
    event = payload["rows"]["event:0022500003:1"]
    assert event["collection"] == "game_events"
    assert event["row_sha256"] == digest(restore["bundle"]["data"]["events"][0])
    assert event["runtime_receipt"] == f"{VERSION}:events:{event['game_id']}:1"
    assert payload["players"]["1628384"]["name"] == "Jalen Brunson"
    assert len(payload["rows"]) == 10
    assert len(payload["players"]) == 2


async def test_changed_sql_value_fails_and_writes_no_rows(restore) -> None:
    async with restore["session"]() as db:
        game = (await db.execute(select(Game).where(Game.nba_game_id == "0022500003"))).scalar_one()
        game.home_score = 120
        await db.commit()
    async with restore["session"]() as db:
        result = await verify_restore(db, restore["bundle"])
    assert result.rows == {}
    assert any("game:0022500003" in p and "home_score" in p for p in result.problems)


async def test_missing_sql_row_fails(restore) -> None:
    async with restore["session"]() as db:
        await db.execute(delete(PeriodScore).where(PeriodScore.period == 1))
        await db.commit()
    async with restore["session"]() as db:
        result = await verify_restore(db, restore["bundle"])
    assert "period:0022500003:NYK:1: missing SQL row" in result.problems


async def test_extra_sql_row_fails(restore) -> None:
    async with restore["session"]() as db:
        game = (await db.execute(select(Game).where(Game.nba_game_id == "0022500018"))).scalar_one()
        db.add(
            PeriodScore(
                release_id=game.release_id, game_id=game.id, team_id="NYK", period=4, points=31
            )
        )
        await db.commit()
    async with restore["session"]() as db:
        result = await verify_restore(db, restore["bundle"])
    assert "period:0022500018:NYK:4: extra SQL row" in result.problems


async def test_duplicate_bundle_row_fails(restore) -> None:
    bundle = dict(restore["bundle"])
    bundle["data"] = {**bundle["data"], "games": [*bundle["data"]["games"], dict(GAME_FIELDS)]}
    async with restore["session"]() as db:
        result = await verify_restore(db, bundle)
    assert "game:0022500003: duplicate canonical row in bundle" in result.problems


async def test_duplicate_sql_row_fails(restore) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{restore['database']}")
    async with engine.begin() as connection:
        await connection.exec_driver_sql("DROP INDEX uq_games_release_nba_game")
    await engine.dispose()
    async with restore["session"]() as db:
        games = select(Game).where(Game.nba_game_id == "0022500003")
        clone = (await db.execute(games)).scalar_one()
        db.add(
            Game(
                release_id=clone.release_id,
                nba_game_id="0022500003",
                season=clone.season,
                game_date=clone.game_date,
                home_team_id="NYK",
                away_team_id="BOS",
                home_score=119,
                away_score=111,
                status="final",
                season_type="regular",
                data_status="analysis_ready",
            )
        )
        await db.commit()
    async with restore["session"]() as db:
        result = await verify_restore(db, restore["bundle"])
    assert "game:0022500003: duplicate SQL rows" in result.problems


async def test_wrong_relational_player_fails(restore) -> None:
    async with restore["session"]() as db:
        other_query = select(Player).where(Player.nba_player_id == 1626157)
        other = (await db.execute(other_query)).scalar_one()
        game_query = select(Game).where(Game.nba_game_id == "0022500003")
        game = (await db.execute(game_query)).scalar_one()
        existing = (
            await db.execute(
                select(PlayerGameStat).where(
                    PlayerGameStat.game_id == game.id, PlayerGameStat.player_id == other.id
                )
            )
        ).scalar_one()
        await db.delete(existing)
        row = (
            await db.execute(
                select(PlayerGameStat).where(
                    PlayerGameStat.game_id == game.id, PlayerGameStat.points == 24
                )
            )
        ).scalar_one()
        row.player_id = other.id
        await db.commit()
    async with restore["session"]() as db:
        result = await verify_restore(db, restore["bundle"])
    assert "box:0022500003:1628384: missing SQL row" in result.problems
    assert any(
        "box:0022500003:1626157: field points differs" in problem for problem in result.problems
    )


async def test_label_reference_hash_mismatch_fails(restore) -> None:
    async with restore["session"]() as db:
        result = await verify_restore(
            db, restore["bundle"], label_references=[("game:0022500003", "0" * 64)]
        )
    assert result.problems == ("game:0022500003: label reference hash mismatch",)


async def test_release_manifest_mismatch_fails(restore) -> None:
    async with restore["session"]() as db:
        release = (await db.execute(select(DatasetRelease))).scalar_one()
        release.manifest_sha256 = "1" * 64
        await db.commit()
    async with restore["session"]() as db:
        result = await verify_restore(db, restore["bundle"])
    assert "release manifest sha256 does not match the approved bundle" in result.problems


def test_loopback_dsn_guard_rejects_non_loopback_and_other_backends() -> None:
    assert loopback_dsn("postgresql://u:p@127.0.0.1:18430/knicksiq").host == "127.0.0.1"
    assert loopback_dsn("postgresql+asyncpg://u:p@localhost:18430/knicksiq").host == "localhost"
    for rejected in (
        "postgresql://u:p@db.internal:5432/knicksiq",
        "sqlite:///tmp/x.sqlite",
        "",
    ):
        with pytest.raises(VerificationError):
            loopback_dsn(rejected)


def test_cli_requires_an_explicit_local_dsn() -> None:
    assert main([]) == 2
    assert main(["--dsn", "postgresql://u:p@10.0.0.5:5432/knicksiq"]) == 2


def test_cli_fails_without_writing_when_the_database_is_unreachable(tmp_path: Path, capsys) -> None:
    output = tmp_path / "runtime-mapping.json"
    report = tmp_path / "runtime-mapping-verification.json"
    code = main(
        [
            "--dsn",
            "postgresql://u:p@127.0.0.1:1/knicksiq",
            "--bundle",
            str(tmp_path / "absent.json.gz"),
            "--output",
            str(output),
            "--report",
            str(report),
        ]
    )
    assert code == 1
    assert "bundle not found" in capsys.readouterr().err
    assert not output.exists()
    assert not report.exists()
