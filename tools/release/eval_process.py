"""Local scoping, explicit environments and process control for an evaluation run.

Every rule here exists so one evaluation run cannot reach shared state: the
database and the monthly-budget Redis must be loopback, the candidate is started
with a fully explicit environment that never inherits ``.env`` or an ambient
proxy, readiness can only be answered by the child that was handed the socket,
and stopping the child escalates without ever aborting the evidence.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.evaluation.candidate_proof import ENV_PROOF_KEY
from app.evaluation.provider_guard import (
    ENV_CONFIG,
    ENV_CONFIG_SHA256,
    RunBinding,
    is_loopback_host,
)

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "apps/api"
POSTGRES_SCHEMES = frozenset({"postgresql", "postgres"})
REDIS_SCHEMES = frozenset({"redis", "rediss"})
PROVIDER_KEY_ENV = "KNICKSIQ_EVAL_PROVIDER_KEY"
DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
ARTIFACTS = {
    "report": "report.json",
    "responses": "responses.jsonl",
    "api_log": "api.log",
    "run_config": "run-config.json",
    "approval": "approval.json",
}


class RunnerFailure(RuntimeError):
    """The candidate API, the database scope or the collection did not satisfy the run."""


def validate_db_url(db_url: str) -> str:
    """Only a loopback PostgreSQL DSN may be written by an evaluation run."""
    parts = urlsplit(db_url)
    scheme = parts.scheme.split("+", 1)[0]
    if scheme not in POSTGRES_SCHEMES:
        raise RunnerFailure(
            f"{parts.scheme or 'no scheme'} is not PostgreSQL; the evaluation writes a "
            "disposable local PostgreSQL database only"
        )
    host = parts.hostname
    if not host:
        raise RunnerFailure(
            "the database URL must name an explicit loopback host; unix sockets and "
            "host-less DSNs are refused"
        )
    if not is_loopback_host(host):
        raise RunnerFailure(
            f"{host} is not a loopback host; a remote database is never read or written by "
            "this run (any loopback address, ::1 or localhost)"
        )
    if not parts.path.strip("/"):
        raise RunnerFailure("the database URL must name the database itself")
    overrides = parse_qs(parts.query)
    for key in ("host", "hostaddr"):
        for value in overrides.get(key, []):
            if not is_loopback_host(value):
                raise RunnerFailure(f"{key}={value} redirects the run off loopback; refused")
    return db_url


def validate_redis_url(redis_url: str) -> str:
    """The application monthly-budget ledger needs a local Redis, never a remote one."""
    parts = urlsplit(redis_url)
    if parts.scheme not in REDIS_SCHEMES:
        raise RunnerFailure(f"{parts.scheme or 'no scheme'} is not a Redis URL")
    if not is_loopback_host(parts.hostname):
        raise RunnerFailure(
            f"{parts.hostname or redis_url} is not a loopback Redis; a service run keeps its "
            "budget ledger on this machine only"
        )
    return redis_url


class _LocalOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect could move a loopback request off the candidate; it is refused."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str):
        raise RunnerFailure(
            f"candidate API answered {code} redirect to {newurl}; redirects are refused"
        )


def direct_opener() -> urllib.request.OpenerDirector:
    """An opener that never consults ambient proxy settings and never follows redirects."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _LocalOnlyRedirects())


@dataclass(frozen=True)
class ServiceSettings:
    """Everything a service candidate needs, all of it explicit operator input."""

    binding: RunBinding
    api_key: str
    redis_url: str
    config_path: Path


def clean_env(
    db_url: str,
    *,
    loop_enabled: bool,
    service: ServiceSettings | None = None,
    proof_key: str = "",
) -> dict[str, str]:
    """Explicit settings only: a local `.env` must never leak into an evaluation run."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(API_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "ENVIRONMENT": "development",
        "DEBUG": "false",
        "LOG_JSON": "false",
        "LOG_LEVEL": "WARNING",
        "DB_URL": db_url,
        "DB_ECHO": "false",
        "REDIS_URL": "",
        "RAG_QDRANT_ENABLED": "false",
        "RAG_QDRANT_CLOUD_INFERENCE": "false",
        "AI_PROVIDER": "mock",
        "AI_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "ANALYST_EVIDENCE_LOOP_ENABLED": "true" if loop_enabled else "false",
        "ANALYSIS_ANSWER_MODE": "deterministic",
        "REQUIRE_ACTIVE_RELEASE": "true",
        "SEED_ON_STARTUP": "false",
        "PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE": "1000",
        "PUBLIC_CHAT_RATE_LIMIT_PER_DAY": "10000",
    }
    if service is not None:
        binding = service.binding
        # The real provider path: explicit origin, explicit model, the operator's key, and
        # loopback Redis for the existing monthly budget. Cloud inference bills separately.
        env.update(
            {
                "REDIS_URL": service.redis_url,
                "AI_PROVIDER": "openrouter",
                "AI_API_KEY": service.api_key,
                "AI_BASE_URL": binding.provider_base_url,
                "AI_CHAT_MODEL": binding.provider_model,
                "OPENROUTER_ALLOWED_MODELS": json.dumps([binding.provider_model]),
                "ANALYSIS_ANSWER_MODE": "llm_primary",
                ENV_CONFIG: str(service.config_path),
                ENV_CONFIG_SHA256: binding.config_sha256,
            }
        )
        if binding.reasoning_effort is not None:
            env["AI_REASONING_EFFORT"] = binding.reasoning_effort
        # The run's private key reaches the candidate's memory only: never an artifact, never
        # a log line, never the collector. Without it the entrypoint refuses to answer.
        if proof_key:
            env[ENV_PROOF_KEY] = proof_key
    return env


def bind_listener() -> socket.socket:
    """Bind the exact socket the child serves on, so no other process can answer for it."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.set_inheritable(True)
    return listener


def wait_ready(base_url: str, process: subprocess.Popen[str], deadline: float) -> dict[str, Any]:
    """Wait for the child's own readiness; a foreign listener or a dead child never passes."""
    opener = direct_opener()
    last: str = "no response"
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            raise RunnerFailure(f"API exited early with code {code}")
        try:
            with opener.open(f"{base_url}/health/ready", timeout=5) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = type(exc).__name__
        else:
            if isinstance(body, dict) and body.get("status") == "ready":
                return body
            last = json.dumps(body)[:400]
        time.sleep(0.5)
    raise RunnerFailure(f"API never became ready: {last}")


def stop_process(process: subprocess.Popen[str], *, grace: float = 15.0) -> list[str]:
    """Stop the child's whole process group. Never raises; every residue is reported."""
    problems: list[str] = []
    if process.poll() is not None:
        return problems
    try:
        group = os.getpgid(process.pid)
    except ProcessLookupError:
        return problems
    own_group = os.getpgid(0)

    def signal_group(sig: int, label: str) -> None:
        try:
            if group == own_group:
                process.send_signal(sig)
            else:
                os.killpg(group, sig)
        except ProcessLookupError:
            return
        except OSError as exc:
            problems.append(f"{label}: {exc}")

    signal_group(signal.SIGTERM, "terminate")
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        signal_group(signal.SIGKILL, "kill")
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            problems.append(f"child {process.pid} did not exit after SIGKILL")
    if process.poll() is None:
        problems.append(f"child {process.pid} is still running")
    return problems


def run_cli(
    arguments: list[str], *, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "app.evaluation.cli", *arguments],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RunnerFailure(
            f"evaluation CLI failed ({result.returncode}): "
            f"{(result.stderr or result.stdout)[-1500:]}"
        )
    return result


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}:{parts.port}/{parts.path.lstrip('/')}"


def relative_artifacts(output: Path) -> dict[str, str]:
    """Artifact names relative to the summary, for the files this run actually wrote."""
    artifacts = {name: file for name, file in ARTIFACTS.items() if (output / file).exists()}
    artifacts["output_dir"] = os.path.relpath(output, Path.cwd())
    return artifacts


def interrupt(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt(f"signal {signum}")


__all__ = [
    "API_ROOT",
    "ARTIFACTS",
    "DEFAULT_REDIS_URL",
    "PROVIDER_KEY_ENV",
    "REPO",
    "RunnerFailure",
    "ServiceSettings",
    "bind_listener",
    "clean_env",
    "direct_opener",
    "interrupt",
    "redact_url",
    "relative_artifacts",
    "run_cli",
    "stop_process",
    "validate_db_url",
    "validate_redis_url",
    "wait_ready",
]
