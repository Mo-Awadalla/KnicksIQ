"""Redis process, seeded tools and scripted model fixtures for analyst integration."""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess

import pytest
from app.services import analyst_budget
from app.services.analyst_tools import AnalystTools
from app.tests.support.player_archive import _seed_release_stats
from redis.asyncio import Redis


@pytest.fixture
async def local_redis(monkeypatch, tmp_path):
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("redis-server is required for atomic concurrency integration tests")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            binary,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--save",
            "",
            "--appendonly",
            "no",
            "--dir",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def connection():
        return Redis.from_url(f"redis://127.0.0.1:{port}", socket_timeout=1)

    redis = await connection()
    try:
        for _ in range(100):
            try:
                await redis.ping()
                break
            except ConnectionError:
                await asyncio.sleep(0.01)
            except Exception:
                await asyncio.sleep(0.01)
        for module in (analyst_budget,):
            monkeypatch.setattr(module, "_redis", connection)
        yield redis
    finally:
        await redis.aclose()
        process.terminate()
        process.wait(timeout=5)


async def make_tools(db, question="Give me an interesting stat", state=None):
    release, player = await _seed_release_stats(db)
    tools = AnalystTools(db, release, question, release.season, state or {})
    await tools.prepare()
    return tools, player
