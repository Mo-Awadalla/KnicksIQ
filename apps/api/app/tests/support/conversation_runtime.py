from __future__ import annotations

import argparse
import asyncio
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from app.tests.support.redis_fault_proxy import RedisFaultProxy

API_ROOT = Path(__file__).resolve().parents[3]
MODEL = "deepseek/deepseek-v4.1-flash"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def database_url(directory: Path) -> str:
    url = os.environ.get("CHAT_E2E_DATABASE_URL")
    if not url:
        return f"sqlite+aiosqlite:///{directory / 'chat.sqlite3'}"
    parsed = urlsplit(url)
    name = parsed.path.removeprefix("/")
    if (
        parsed.scheme not in {"postgresql", "postgresql+asyncpg"}
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or not name.startswith("knicksiq_rehaul_")
        or not name.isascii()
        or not name.replace("_", "").isalnum()
        or len(name) > 63
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "CHAT_E2E_DATABASE_URL must name a loopback knicksiq_rehaul_* PostgreSQL "
            "database without URL options"
        )
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


async def database_command(base_url: str, statement: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(base_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(statement)
    finally:
        await engine.dispose()


async def seed(url: str) -> None:
    from app.core.config import Settings

    Settings.model_config["env_file"] = None
    from app.core.seed_loader import seed_all
    from app.models import Base
    from app.tests.support.player_archive import _seed_release_stats
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            if tables:
                raise RuntimeError("Refusing to seed a nonempty database")
            if connection.dialect.name == "postgresql":
                await connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await seed_all(session)
            await _seed_release_stats(session)
    finally:
        await engine.dispose()


class ConversationRuntime:
    def __init__(
        self,
        directory: Path,
        api_port: int,
        redis_port: int,
        upstream_port: int,
        overrides: dict[str, str] | None = None,
    ):
        self.directory = directory
        self.api_port = api_port
        self.redis_port = redis_port
        self.upstream_port = upstream_port
        self.overrides = overrides or {}
        self.processes: list[subprocess.Popen] = []
        self.url = database_url(directory)
        self.base_database_url = self.url
        self.owned_database: str | None = None
        self.proxy = RedisFaultProxy(redis_port)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def upstream_url(self) -> str:
        return f"http://127.0.0.1:{self.upstream_port}"

    def _spawn(self, args: list[str], env: dict[str, str]) -> None:
        self.processes.append(subprocess.Popen(args, cwd=self.directory, env=env))

    async def _ready(self, url: str) -> None:
        deadline = time.monotonic() + 45
        async with httpx.AsyncClient(timeout=0.5, headers={"X-Forwarded-Proto": "https"}) as client:
            while time.monotonic() < deadline:
                if any(process.poll() is not None for process in self.processes):
                    raise RuntimeError(f"Runtime process exited while waiting for {url}")
                try:
                    response = await client.get(url)
                    if response.is_redirect:
                        raise RuntimeError(
                            f"Readiness returned {response.status_code} "
                            f"to {response.headers.get('location')}"
                        )
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.05)
        raise TimeoutError(url)

    async def start(self) -> ConversationRuntime:
        try:
            if self.url.startswith("postgresql+asyncpg://"):
                from sqlalchemy.engine import make_url

                name = "knicksiq_rehaul_run_" + uuid.uuid4().hex
                await database_command(
                    self.base_database_url, f'CREATE DATABASE "{name}" TEMPLATE template0'
                )
                self.owned_database = name
                self.url = (
                    make_url(self.base_database_url)
                    .set(database=name)
                    .render_as_string(hide_password=False)
                )
            await seed(self.url)
            await self.proxy.start()
            env = {
                key: os.environ[key]
                for key in ("PATH", "HOME", "SYSTEMROOT", "TMPDIR")
                if key in os.environ
            }
            env.update(
                {
                    "PYTHONPATH": str(API_ROOT),
                    "TEST_MODE": "false",
                    "ENVIRONMENT": "production",
                    "DB_URL": self.url,
                    "REDIS_URL": f"redis://127.0.0.1:{self.proxy.port}/0",
                    "AI_PROVIDER": "openai",
                    "AI_API_KEY": "fixture-key",
                    "AI_BASE_URL": self.upstream_url + "/v1",
                    "AI_CHAT_MODEL": MODEL,
                    "OPENROUTER_ALLOWED_MODELS": f'["{MODEL}"]',
                    "OPENROUTER_MONTHLY_CUTOFF_USD": "2",
                    "IP_HASH_SECRET": "disposable-fixture-secret",
                    "PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE": "1000",
                    "PUBLIC_CHAT_RATE_LIMIT_PER_DAY": "10000",
                    "LOG_JSON": "false",
                }
            )
            env.update(self.overrides)
            self._spawn(
                [
                    "redis-server",
                    "--bind",
                    "127.0.0.1",
                    "--port",
                    str(self.redis_port),
                    "--save",
                    "",
                    "--appendonly",
                    "no",
                    "--dir",
                    str(self.directory),
                ],
                env,
            )
            self._spawn(
                [
                    sys.executable,
                    "-m",
                    "app.tests.support.conversation_stream",
                    "--port",
                    str(self.upstream_port),
                ],
                env,
            )
            await self._ready(self.upstream_url + "/__control__/state")
            script = (
                "from app.core.config import Settings; "
                "Settings.model_config['env_file'] = None; import uvicorn; "
                "uvicorn.run('app.main:app', host='127.0.0.1', port="
                + str(self.api_port)
                + ", log_level='warning')"
            )
            self._spawn([sys.executable, "-c", script], env)
            await self._ready(self.base_url + "/health/live")
            return self
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        self.proxy.release()
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
        self.processes.clear()
        await self.proxy.stop()
        if self.owned_database is not None:
            await database_command(self.base_database_url, f'DROP DATABASE "{self.owned_database}"')
            self.owned_database = None


async def serve(args: argparse.Namespace) -> None:
    with tempfile.TemporaryDirectory(prefix="knicksiq-chat-") as directory:
        runtime = ConversationRuntime(
            Path(directory), args.api_port, args.redis_port, args.upstream_port
        )
        await runtime.start()
        done = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, done.set)
        print(f"Conversation runtime ready at {runtime.base_url}", flush=True)
        try:
            await done.wait()
        finally:
            await runtime.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("api", "redis", "upstream"):
        parser.add_argument(f"--{name}-port", type=int, required=True)
    asyncio.run(serve(parser.parse_args()))


if __name__ == "__main__":
    main()
