"""Real socket HTTP harness: uvicorn API, sqlite file, redis, and a blocking fake provider."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from app.tests.support.player_archive import _seed_release_stats

API_ROOT = Path(__file__).resolve().parents[2]
SHADOW_SECRET = "live-shadow-secret"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_http(url: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"{url} did not become ready")


class FakeProvider:
    """OpenAI-compatible endpoint that holds every completion until the test releases it."""

    def __init__(self, *, hold: bool = True):
        from app.tests.support.analyst_protocol import ScriptedAdapter

        self.adapter = ScriptedAdapter()
        self.hold = hold
        self.release = threading.Event()
        self.entered = threading.Event()
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.requests = 0
        self.completed = 0
        self.in_flight = 0
        self.bodies: list[dict] = []
        provider = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with provider.lock:
                    provider.requests += 1
                    provider.in_flight += 1
                    provider.bodies.append(payload)
                provider.entered.set()
                if provider.hold:
                    provider.release.wait(timeout=120)
                try:
                    content = asyncio.run(
                        provider.adapter.generate(
                            system=payload["messages"][0]["content"],
                            user=payload["messages"][1]["content"],
                        )
                    )
                finally:
                    with provider.lock:
                        provider.in_flight -= 1
                data = json.dumps(
                    {
                        "id": "protocol-fixture",
                        "model": "protocol-fixture",
                        "choices": [{"message": {"content": content}}],
                        "usage": {},
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                with provider.lock:
                    provider.completed += 1
                provider.finished.set()

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> FakeProvider:
        self._thread.start()
        return self

    def stop(self) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


class LiveShadowRuntime:
    """One isolated API process with its own sqlite database, redis and provider."""

    def __init__(self, tmp_path: Path, overrides: dict[str, str] | None = None):
        self.db_path = tmp_path / "shadow-live.sqlite3"
        self.redis_port = free_port()
        self.redis_dir = tmp_path / "redis"
        self.redis_dir.mkdir()
        self.provider = FakeProvider().start()
        self._redis = self._start_redis()
        self.port = free_port()
        self.overrides = overrides or {}
        self._process: subprocess.Popen | None = None
        self._stopped = False

    async def start(self) -> LiveShadowRuntime:
        await self._seed_database()
        self._process = self._start_api()
        _wait_for_http(f"http://127.0.0.1:{self.port}/health/live", timeout=60)
        return self

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _start_redis(self) -> subprocess.Popen:
        binary = shutil.which("redis-server")
        if binary is None:
            raise RuntimeError("redis-server is required for the live shadow protocol check")
        process = subprocess.Popen(
            [
                binary,
                "--bind",
                "127.0.0.1",
                "--port",
                str(self.redis_port),
                "--save",
                "",
                "--appendonly",
                "no",
                "--dir",
                str(self.redis_dir),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", self.redis_port)) == 0:
                    return process
            time.sleep(0.05)
        process.terminate()
        raise TimeoutError("redis-server did not start")

    async def _seed_database(self) -> None:
        from app.core.seed_loader import seed_all
        from app.models import Base
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with session_factory() as db:
            await seed_all(db)
            await _seed_release_stats(db)
        await engine.dispose()

    def _environment(self) -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            not in {
                "TEST_MODE",
                "DB_URL",
                "DATABASE_URL",
                "REDIS_URL",
                "AI_PROVIDER",
                "AI_API_KEY",
                "AI_BASE_URL",
                "AI_CHAT_MODEL",
                "OPENROUTER_API_KEY",
                "ANALYSIS_ANSWER_MODE",
                "ANALYSIS_SHADOW_SAMPLE_RATE",
                "ANALYST_EVIDENCE_LOOP_ENABLED",
                "ANALYST_DEADLINE_SECONDS",
                "LOG_JSON",
                "IP_HASH_SECRET",
                "SENTRY_DSN",
            }
        }
        environment.update(
            {
                "TEST_MODE": "false",
                "DB_URL": f"sqlite+aiosqlite:///{self.db_path}",
                "REDIS_URL": f"redis://127.0.0.1:{self.redis_port}/0",
                "AI_PROVIDER": "openai",
                "AI_API_KEY": "protocol-fixture-key",
                "AI_BASE_URL": self.provider.base_url,
                "AI_CHAT_MODEL": "protocol-fixture",
                "AI_REQUEST_TIMEOUT_SECONDS": "25",
                "ANALYSIS_ANSWER_MODE": "shadow",
                "ANALYSIS_SHADOW_SAMPLE_RATE": "1.0",
                "ANALYST_EVIDENCE_LOOP_ENABLED": "true",
                "ANALYST_DEADLINE_SECONDS": "30",
                "ANALYST_PROVIDER_FORMAT": "json_object",
                "LOG_JSON": "false",
                "LOG_LEVEL": "WARNING",
                "IP_HASH_SECRET": SHADOW_SECRET,
                "PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE": "50",
            }
        )
        environment.update(self.overrides)
        return environment

    def _start_api(self) -> subprocess.Popen:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=API_ROOT,
            env=self._environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        self.provider.stop()
        self._redis.terminate()
        self._redis.wait(timeout=10)
