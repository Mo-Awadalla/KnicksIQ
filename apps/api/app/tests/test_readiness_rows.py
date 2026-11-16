"""Run the readiness CLI against a real local API and disposable PostgreSQL rows."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import asyncpg
import httpx
import pytest
from app.models import Base
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.team import Team
from app.services.release_bundle import canonical_json
from sqlalchemy import update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[4]
VERSION = "2025-26.readiness-regression"


async def _database_command(dsn: str, command: str) -> None:
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(command)
    finally:
        await connection.close()


async def _seed(dsn: str, sha256: str, content: dict) -> None:
    from datetime import date

    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine)() as session:
            session.add(
                DatasetRelease(
                    version=VERSION,
                    season="2025-26",
                    source="readiness-regression",
                    manifest_sha256=sha256,
                    status="active",
                    validation_passed=True,
                )
            )
            session.add_all([Team(**row) for row in content["teams"]])
            await session.flush()
            game = dict(content["games"][0])
            game["game_date"] = date.fromisoformat(game["game_date"])
            session.add(Game(release_id=1, **game))
            await session.commit()
    finally:
        await engine.dispose()


async def _alter(dsn: str, model, **values) -> None:
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            await connection.execute(update(model).values(**values))
    finally:
        await engine.dispose()


def test_readiness_cli_checks_actual_rows_and_api_database(tmp_path: Path) -> None:
    explicit = os.environ.get("READINESS_TEST_DATABASE_URL")
    if not explicit:
        pytest.skip("requires an explicitly authorized local disposable PostgreSQL server")
    base = make_url(explicit)
    assert base.get_backend_name() == "postgresql"
    assert base.host in {"127.0.0.1", "localhost", "::1"}
    admin = base.set(drivername="postgresql").render_as_string(hide_password=False)
    database = "readiness_rows_" + uuid.uuid4().hex
    foreign = database + "_foreign"
    dsn = base.set(database=database, drivername="postgresql+asyncpg").render_as_string(
        hide_password=False
    )
    foreign_dsn = base.set(database=foreign, drivername="postgresql+asyncpg").render_as_string(
        hide_password=False
    )
    content = {
        "games": [
            {
                "nba_game_id": "0022500003",
                "game_date": "2025-10-22",
                "season": "2025-26",
                "season_type": "regular",
                "status": "final",
                "home_team_id": "NYK",
                "away_team_id": "BOS",
                "home_score": 119,
                "away_score": 111,
                "data_status": "analysis_ready",
            }
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
    bundle = tmp_path / "bundle.json.gz"
    bundle.write_bytes(
        gzip.compress(
            canonical_json(
                {
                    "manifest": {
                        "version": VERSION,
                        "content_sha256": hashlib.sha256(canonical_json(content)).hexdigest(),
                    },
                    "data": content,
                }
            ),
            mtime=0,
        )
    )
    sha256 = hashlib.sha256(bundle.read_bytes()).hexdigest()
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "PYTHONPATH": os.pathsep.join(
            [str(ROOT / "apps/api"), str(ROOT / "packages/basketball-core/src")]
        ),
        "DB_URL": dsn,
        "ENVIRONMENT": "production",
        "TEST_MODE": "false",
        "SEED_ON_STARTUP": "false",
        "DEBUG": "false",
        "LOG_LEVEL": "WARNING",
        "AI_PROVIDER": "none",
        "OPENROUTER_API_KEY": "",
        "AI_API_KEY": "",
        "RAG_QDRANT_ENABLED": "false",
        "REDIS_URL": "",
        "SENTRY_DSN": "",
        "IP_HASH_SECRET": "readiness-fixture-only-not-production",
        "CORS_ORIGINS": '["https://www.knicksiq.win"]',
        "PUBLIC_WEB_ORIGIN": "https://www.knicksiq.win",
    }
    created: list[str] = []
    process = None
    try:
        for name, url in ((database, dsn), (foreign, foreign_dsn)):
            asyncio.run(_database_command(admin, f'CREATE DATABASE "{name}"'))
            created.append(name)
            asyncio.run(_seed(url, sha256, content))
        with (tmp_path / "api.log").open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                cwd=tmp_path,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            with httpx.Client(trust_env=False, headers={"X-Forwarded-Proto": "https"}) as client:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    assert process.poll() is None, (tmp_path / "api.log").read_text()
                    try:
                        if client.get(base_url + "/health/ready", timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail((tmp_path / "api.log").read_text())

                def check(name: str, expected: bool, url: str = dsn) -> dict:
                    output = tmp_path / f"{name}.json"
                    completed = subprocess.run(
                        [
                            sys.executable,
                            str(ROOT / "tools/release/readiness.py"),
                            "--base-url",
                            base_url,
                            "--local-https-proxy",
                            "--bundle",
                            str(bundle),
                            "--sha256",
                            sha256,
                            "--dsn",
                            url,
                            "--api-pid",
                            str(process.pid),
                            "--output",
                            str(output),
                        ],
                        cwd=ROOT,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    assert completed.returncode == (0 if expected else 1), (
                        completed.stdout + completed.stderr
                    )
                    report = json.loads(output.read_text())
                    assert report["passed"] is expected
                    return report

                valid = check("valid", True)
                rows = next(item for item in valid["checks"] if item["name"] == "database_rows")
                assert rows["evidence"]["rows_verified"] == 1
                assert rows["evidence"]["collections"]["games"] == 1
                foreign_report = check("foreign", False, foreign_dsn)
                assert "API database" in foreign_report["error"]["message"]
                asyncio.run(_alter(dsn, Game, home_score=120))
                assert client.get(base_url + "/health/ready").json()["data_version"] == VERSION
                corrupt = check("corrupt-score", False)
                assert "home_score differs" in json.dumps(corrupt)
                asyncio.run(_alter(dsn, Game, home_score=119))
                asyncio.run(_alter(dsn, DatasetRelease, manifest_sha256="0" * 64))
                wrong_hash = check("wrong-original-hash", False)
                assert "manifest sha256" in json.dumps(wrong_hash)
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=15)
        for name in reversed(created):
            asyncio.run(_database_command(admin, f'DROP DATABASE "{name}" WITH (FORCE)'))
