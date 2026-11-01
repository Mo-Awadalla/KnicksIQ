"""Repeatable real-local HTTP scenario for the production container contract.

This starts the real application in a separate process with production settings
(``ENVIRONMENT=production``, HTTPS redirect, validated active release) on a loopback
socket, then asserts over actual HTTP what the Docker health probe and the public
directory contract require:

* a plaintext request is still redirected to HTTPS, so the contract is not weakened;
* a loopback probe that presents the trusted-edge scheme header reaches liveness and
  readiness, which is what the container ``HEALTHCHECK`` sends;
* only active validated release membership is served across multiple releases;
* the in-process limiter answers real requests from a real socket.

The database is a disposable SQLite file and Redis is unset, so nothing here touches
a real deployment, provider, or shared database.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from app.core.seed_loader import seed_all
from app.models import Base
from app.models.box_score import PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.models.team import Team
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).parents[4]
API_ROOT = REPO_ROOT / "apps" / "api"
CORE_ROOT = REPO_ROOT / "packages" / "basketball-core" / "src"
ACTIVE_VERSION = "scenario-active.1"
STAGED_VERSION = "scenario-staged.1"
PROBE_HEADERS = {"X-Forwarded-Proto": "https"}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


async def _prepare_database(db_path: Path) -> dict[str, int]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with sessions() as db:
            await seed_all(db)
            active = DatasetRelease(
                version=ACTIVE_VERSION,
                season="2025-26",
                source="live-scenario",
                manifest_sha256=_digest(ACTIVE_VERSION),
                validation_passed=True,
                status="active",
            )
            staged = DatasetRelease(
                version=STAGED_VERSION,
                season="2025-26",
                source="live-scenario",
                manifest_sha256=_digest(STAGED_VERSION),
                validation_passed=True,
                status="staged",
            )
            db.add_all([active, staged])
            await db.flush()
            games = (await db.execute(select(Game).order_by(Game.id))).scalars().all()
            await db.execute(update(Game).values(release_id=active.id))

            brunson_id = (
                await db.execute(select(Player.id).where(Player.full_name == "Jalen Brunson"))
            ).scalar_one()
            staged_player = Player(
                nba_player_id=1919001,
                full_name="Staged Only Guard",
                team_id="NYK",
                position="PG",
            )
            staged_team = Team(
                id="ZZZ",
                nba_team_id=1999001,
                name="Ghosts",
                city="Nowhere",
                abbreviation="ZZZ",
            )
            db.add_all([staged_player, staged_team])
            await db.flush()
            db.add_all(
                [
                    PlayerGameStat(
                        release_id=active.id,
                        game_id=games[0].id,
                        player_id=brunson_id,
                        team_id="NYK",
                        starter=True,
                        minutes=34.0,
                        points=28,
                    ),
                    PlayerGameStat(
                        release_id=staged.id,
                        game_id=games[0].id,
                        player_id=staged_player.id,
                        team_id="NYK",
                        minutes=22.0,
                        points=9,
                    ),
                    TeamGameStat(
                        release_id=staged.id,
                        game_id=games[0].id,
                        team_id="ZZZ",
                        points=77,
                    ),
                ]
            )
            await db.commit()
            return {
                "brunson_id": brunson_id,
                "staged_player_id": staged_player.id,
                "games": len(games),
            }
    finally:
        await engine.dispose()


def _child_environment(db_path: Path) -> dict[str, str]:
    """A deliberately explicit environment: never inherit the developer `.env`."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "PYTHONPATH": os.pathsep.join([str(API_ROOT), str(CORE_ROOT)]),
        "PYTHONUNBUFFERED": "1",
        "TEST_MODE": "false",
        "ENVIRONMENT": "production",
        "DEBUG": "false",
        "LOG_LEVEL": "WARNING",
        "LOG_JSON": "false",
        "DB_URL": f"sqlite+aiosqlite:///{db_path}",
        "REQUIRE_ACTIVE_RELEASE": "true",
        "SEED_ON_STARTUP": "false",
        "IP_HASH_SECRET": _digest("scenario-ip-hash-secret"),
        "CORS_ORIGINS": '["https://www.knicksiq.win"]',
        "PUBLIC_WEB_ORIGIN": "https://www.knicksiq.win",
        "TRUSTED_HOSTS": '["127.0.0.1","localhost"]',
        "AI_PROVIDER": "mock",
        "ANALYSIS_ANSWER_MODE": "deterministic",
        "ANALYST_EVIDENCE_LOOP_ENABLED": "false",
        "RAG_QDRANT_ENABLED": "false",
        "RAG_HYBRID_ENABLED": "false",
        "RAG_LLM_PLANNER_ENABLED": "false",
        "PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE": "2",
        "PUBLIC_CHAT_RATE_LIMIT_PER_DAY": "100",
    }


@pytest.fixture(scope="module")
def live_api(tmp_path_factory) -> Iterator[SimpleNamespace]:
    workdir = tmp_path_factory.mktemp("live-release-scenario")
    db_path = workdir / "release.db"
    seeded = asyncio.run(_prepare_database(db_path))
    port = _free_port()
    log_path = workdir / "server.log"
    log_file = log_path.open("w")
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
        cwd=workdir,
        env=_child_environment(db_path),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        started = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                httpx.get(f"{base_url}/health/live", headers=PROBE_HEADERS, timeout=0.5)
                started = True
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        if not started:
            log_file.flush()
            pytest.fail(f"live API did not start:\n{log_path.read_text()[-4000:]}")
        yield SimpleNamespace(base_url=base_url, port=port, **seeded)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive cleanup
            process.kill()
            process.wait(timeout=10)
        log_file.close()


def test_plaintext_requests_are_still_redirected_to_https(live_api):
    response = httpx.get(f"{live_api.base_url}/health/live")
    assert response.status_code in {307, 308}
    assert response.headers["location"].startswith("https://")


def test_loopback_probe_header_reaches_liveness_and_readiness(live_api):
    live = httpx.get(f"{live_api.base_url}/health/live", headers=PROBE_HEADERS)
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}

    ready = httpx.get(f"{live_api.base_url}/health/ready", headers=PROBE_HEADERS)
    assert ready.status_code == 200
    body = ready.json()
    assert body["required_failures"] == []
    assert body["data_version"] == ACTIVE_VERSION


def test_container_healthcheck_exit_code_against_the_real_process(live_api):
    from app.api.health_probe import probe

    assert probe(port=str(live_api.port)) == 0
    assert probe(port=str(_free_port())) == 1


def test_directories_serve_only_the_active_release(live_api):
    players = httpx.get(f"{live_api.base_url}/players", headers=PROBE_HEADERS)
    assert players.status_code == 200
    assert [player["id"] for player in players.json()] == [live_api.brunson_id]

    staged = httpx.get(
        f"{live_api.base_url}/players/{live_api.staged_player_id}", headers=PROBE_HEADERS
    )
    assert staged.status_code == 404

    member = httpx.get(f"{live_api.base_url}/players/{live_api.brunson_id}", headers=PROBE_HEADERS)
    assert member.status_code == 200
    assert member.json()["full_name"] == "Jalen Brunson"

    teams = httpx.get(f"{live_api.base_url}/teams", headers=PROBE_HEADERS)
    assert teams.status_code == 200
    team_ids = {team["id"] for team in teams.json()}
    assert "NYK" in team_ids
    assert "ZZZ" not in team_ids

    unknown = httpx.get(f"{live_api.base_url}/teams/ZZZ", headers=PROBE_HEADERS)
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "http_404"

    known = httpx.get(f"{live_api.base_url}/teams/NYK", headers=PROBE_HEADERS)
    assert known.status_code == 200


def test_real_socket_rate_limit_is_per_connection_identity(live_api):
    url = f"{live_api.base_url}/analysis/query"
    payload = {"question": "hi"}
    statuses = [
        httpx.post(url, json=payload, headers=PROBE_HEADERS, timeout=30).status_code
        for _ in range(2)
    ]
    assert 429 not in statuses

    # Redis is unset in this scenario, so the in-process limiter is the only bound.
    assert httpx.post(url, json=payload, headers=PROBE_HEADERS, timeout=30).status_code == 429
    # The identity is the resolved connection address: the same peer stays limited.
    assert httpx.post(url, json=payload, headers=PROBE_HEADERS, timeout=30).status_code == 429


def test_forwarded_identity_is_decided_by_the_trusted_proxy_not_the_app(live_api):
    """The application never parses forwarded headers itself.

    Uvicorn replaces the connection address with a forwarded address only for a
    trusted peer, which here is loopback. The container health probe relies on that
    same trust to present the edge scheme. In production the only trusted peer must
    be the Render edge, which appends the real client address; see
    docs/production-runbook.md.
    """
    url = f"{live_api.base_url}/analysis/query"
    payload = {"question": "hi"}
    response = httpx.post(
        url,
        json=payload,
        headers={**PROBE_HEADERS, "X-Forwarded-For": "198.51.100.99"},
        timeout=30,
    )
    assert response.status_code == 200
