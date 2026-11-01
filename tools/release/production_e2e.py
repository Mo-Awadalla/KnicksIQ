"""Run the built browser and public API against an isolated approved archive.

The driver only allocates local resources. It reads the selected Docker context
and daemon endpoint without changing global Docker configuration, rejects any
nonlocal daemon before creating a container, and pins the validated endpoint for
every Docker command it runs, including the Playwright session eviction helper.
It removes inherited HTTP proxies and TLS overrides from its own API probes and
from every child process.

Docker Desktop networking is required: the nginx container reaches the host API
through ``host.docker.internal``. Native Linux Docker does not provide that
gateway by default, so the browser evidence covers Docker Desktop workstations
only until an explicit Linux host gateway is configured and exercised.

Failure paths are deliberate: interruption becomes a failed verdict, every
teardown step is attempted independently, and cleanup failures are recorded in
``verdict.json`` rather than hidden. Local paths are redacted from artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = "release-artifacts/2025-26/reliability-approved-20260928.json.gz"
BUNDLE_SHA256 = "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"

PROXY_VARIABLES = frozenset({"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY", "NO_PROXY"})
TLS_VARIABLES = frozenset(
    {
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "NODE_TLS_REJECT_UNAUTHORIZED",
    }
)
DOCKER_VARIABLES = frozenset({"DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"})
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


class DriverInterrupted(RuntimeError):
    pass


def redact(text: str) -> str:
    for prefix in (str(ROOT), str(Path.home())):
        text = text.replace(prefix, "<local>")
    return text


def inherited_environment() -> dict[str, str]:
    blocked = PROXY_VARIABLES | TLS_VARIABLES
    return {key: value for key, value in os.environ.items() if key.upper() not in blocked}


def _validated_endpoint(host: str) -> str:
    parsed = urlsplit(host)
    scheme = parsed.scheme.lower()
    if scheme == "unix":
        path = parsed.path
        if not path or not Path(path).is_absolute() or not Path(path).is_socket():
            raise RuntimeError(
                f"Docker unix endpoint {path or host!r} is not an existing local socket"
            )
        return f"unix://{path}"
    if scheme == "tcp":
        name = parsed.hostname or ""
        if name in LOOPBACK_NAMES and parsed.port:
            return f"tcp://{f'[{name}]' if ':' in name else name}:{parsed.port}"
        raise RuntimeError(
            f"Docker TCP endpoint {name or host!r} is not a loopback address; refusing to allocate"
        )
    raise RuntimeError(
        f"Docker endpoint {host!r} is not a local unix socket or loopback TCP address; "
        "refusing to allocate"
    )


def local_daemon_endpoint(environment: dict[str, str]) -> str:
    host = environment.get("DOCKER_HOST", "").strip()
    if host:
        return _validated_endpoint(host)
    context = environment.get("DOCKER_CONTEXT", "").strip()
    if not context:
        context = _docker_read(["context", "show"], environment)
    raw = _docker_read(
        ["context", "inspect", context, "--format", "{{json .Endpoints.docker.Host}}"],
        environment,
    )
    try:
        reported = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Docker context {context!r} endpoint is not readable JSON") from exc
    if not isinstance(reported, str) or not reported.strip():
        raise RuntimeError(f"Docker context {context!r} reports no daemon endpoint")
    return _validated_endpoint(reported.strip())


def _docker_read(arguments: list[str], environment: dict[str, str]) -> str:
    completed = subprocess.run(
        ["docker", *arguments], env=environment, capture_output=True, text=True, timeout=20
    )
    if completed.returncode != 0:
        raise RuntimeError(f"docker {' '.join(arguments)} failed: {completed.stderr.strip()[:400]}")
    return completed.stdout.strip()


def scenario_environment(
    inherited: dict[str, str],
    endpoint: str,
    identity: str,
    ports: dict[str, int],
    api_url: str,
    web_url: str,
    output: Path,
) -> dict[str, str]:
    inherited = {
        key: value for key, value in inherited.items() if key.upper() not in DOCKER_VARIABLES
    }
    return {
        **inherited,
        "DOCKER_HOST": endpoint,
        "ENVIRONMENT": "production",
        "DEBUG": "false",
        "LOG_JSON": "true",
        "TEST_MODE": "false",
        "SEED_ON_STARTUP": "false",
        "DB_URL": f"postgresql+asyncpg://knicksiq:local-e2e-only@127.0.0.1:{ports['pg']}/knicksiq",
        "REDIS_URL": f"redis://127.0.0.1:{ports['redis']}/0",
        "AI_PROVIDER": "none",
        "AI_BASE_URL": "",
        "AI_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "QDRANT_URL": "",
        "QDRANT_API_KEY": "",
        "QDRANT_HOST": "localhost",
        "ADMIN_API_KEY": "",
        "SENTRY_DSN": "",
        "RAG_QDRANT_ENABLED": "false",
        "RAG_HYBRID_ENABLED": "false",
        "RAG_LLM_PLANNER_ENABLED": "false",
        "ANALYST_EVIDENCE_LOOP_ENABLED": "true",
        "ANALYSIS_ANSWER_MODE": "shadow",
        "ANALYSIS_SHADOW_SAMPLE_RATE": "0",
        "IP_HASH_SECRET": f"isolated-e2e-{identity}",
        "PUBLIC_WEB_ORIGIN": web_url,
        "CORS_ORIGINS": json.dumps([web_url]),
        "PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE": "1000",
        "PUBLIC_CHAT_RATE_LIMIT_PER_DAY": "10000",
        "VITE_API_URL": "/api",
        "VITE_SENTRY_DSN": "",
        "KNICKSIQ_LIVE_E2E": "1",
        "PLAYWRIGHT_BASE_URL": web_url,
        "KNICKSIQ_LIVE_API_URL": api_url,
        "PLAYWRIGHT_JSON_OUTPUT_FILE": str(output / "browser.json"),
    }


def ensure_ports_free(ports: dict[str, int]) -> None:
    busy = []
    for name, port in ports.items():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                busy.append(f"{name}={port} ({exc.strerror or exc})")
    if busy:
        raise RuntimeError("Local ports are already in use before allocation: " + "; ".join(busy))


def run(command: list[str], env: dict[str, str], cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def wait_ready(
    probe,
    description: str,
    timeout: float = 60,
    process: subprocess.Popen | None = None,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and (code := process.poll()) is not None:
            raise RuntimeError(f"{description} exited with code {code} before readiness")
        try:
            if probe():
                if process is not None and (code := process.poll()) is not None:
                    raise RuntimeError(f"{description} exited with code {code} during readiness")
                return
        except (httpx.HTTPError, OSError):
            pass
        time.sleep(0.25)
    if process is not None and (code := process.poll()) is not None:
        raise RuntimeError(f"{description} exited with code {code} before readiness")
    raise TimeoutError(f"{description} did not become ready")


def local_client(headers: dict[str, str] | None = None) -> httpx.Client:
    return httpx.Client(timeout=2, headers=headers, trust_env=False)


def install_handlers(state: dict) -> dict[int, object]:
    def handle(signum, _frame):
        if state["cleaning"]:
            return
        raise DriverInterrupted(f"received {signal.Signals(signum).name}")

    return {signum: signal.signal(signum, handle) for signum in (signal.SIGTERM, signal.SIGINT)}


def restore_handlers(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def stop_container(name: str, environment: dict[str, str]) -> None:
    inspected = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", name],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if inspected.returncode != 0:
        if "no such" in inspected.stderr.lower():
            return
        raise RuntimeError(f"cannot confirm {name} exists: {inspected.stderr.strip()[:300]}")
    subprocess.run(
        ["docker", "stop", "--time", "10", name],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def teardown(state: dict, environment: dict[str, str]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    api = state["api"]
    if api is not None and api.poll() is None:
        try:
            os.killpg(api.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            failures.append({"resource": "api", "error": redact(f"{type(exc).__name__}: {exc}")})
        else:
            try:
                api.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(api.pid, signal.SIGKILL)
                except OSError as exc:
                    failures.append(
                        {"resource": "api", "error": redact(f"{type(exc).__name__}: {exc}")}
                    )
                try:
                    api.wait(timeout=10)
                except subprocess.TimeoutExpired as exc:
                    failures.append(
                        {"resource": "api", "error": redact(f"{type(exc).__name__}: {exc}")}
                    )
    for name in reversed(state["containers"]):
        try:
            stop_container(name, environment)
        except Exception as exc:  # noqa: BLE001 - every teardown step is attempted
            failures.append({"resource": name, "error": redact(f"{type(exc).__name__}: {exc}")})
    return failures


def write_verdict(output: Path, verdict: dict) -> bool:
    try:
        (output / "verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"Could not write verdict: {redact(str(exc))}", file=sys.stderr)
        return False
    return True


def announce(output: Path) -> None:
    shown = output.relative_to(ROOT) if output.is_relative_to(ROOT) else Path(output.name)
    print(f"Evidence saved to {shown}")


def run_scenario(
    state: dict,
    environment: dict[str, str],
    ports: dict[str, int],
    names: dict[str, str],
    api_url: str,
    web_url: str,
    output: Path,
) -> None:
    for name, image, arguments, container_port in (
        (
            "pg",
            "postgres:18-alpine",
            [
                "-e",
                "POSTGRES_USER=knicksiq",
                "-e",
                "POSTGRES_PASSWORD=local-e2e-only",
                "-e",
                "POSTGRES_DB=knicksiq",
            ],
            5432,
        ),
        ("redis", "redis:7-alpine", [], 6379),
    ):
        state["containers"].append(names[name])
        run(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "--name",
                names[name],
                "-p",
                f"127.0.0.1:{ports[name]}:{container_port}",
                *arguments,
                image,
            ],
            environment,
        )

    def pg_ready() -> bool:
        command = [
            "docker",
            "exec",
            names["pg"],
            "pg_isready",
            "-h",
            "127.0.0.1",
            "-U",
            "knicksiq",
            "-d",
            "knicksiq",
        ]
        completed = subprocess.run(
            command,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        return completed.returncode == 0

    wait_ready(pg_ready, "PostgreSQL", timeout=90)
    offline = {**environment, "ENVIRONMENT": "development"}
    run(["uv", "run", "--frozen", "--all-packages", "alembic", "upgrade", "head"], offline)
    run(
        [
            "uv",
            "run",
            "--frozen",
            "--all-packages",
            "knicksiq-load-release",
            BUNDLE,
            "--sha256",
            BUNDLE_SHA256,
            "--activate",
        ],
        offline,
    )
    with (output / "api.log").open("w") as log:
        state["api"] = subprocess.Popen(
            [
                "uv",
                "run",
                "--frozen",
                "--all-packages",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(ports["api"]),
                "--proxy-headers",
                "--forwarded-allow-ips",
                "*",
            ],
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    with local_client({"X-Forwarded-Proto": "https"}) as client:
        wait_ready(
            lambda: client.get(api_url + "/health/ready").status_code == 200,
            "API",
            process=state["api"],
        )
    run(["pnpm", "build"], environment, ROOT / "apps/web")
    with tempfile.TemporaryDirectory(prefix="kiq-e2e-") as temporary:
        config = Path(temporary) / "nginx.conf"
        config.write_text(
            "server {\n"
            "    listen 8080;\n"
            "    root /usr/share/nginx/html;\n"
            "    index index.html;\n"
            "    location /api/ {\n"
            f"        proxy_pass http://host.docker.internal:{ports['api']}/;\n"
            "        proxy_set_header Host localhost;\n"
            "        proxy_set_header X-Forwarded-Proto https;\n"
            "    }\n"
            "    location / { try_files $uri $uri/ /index.html; }\n"
            "}\n"
        )
        state["containers"].append(names["web"])
        run(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "--name",
                names["web"],
                "-p",
                f"127.0.0.1:{ports['web']}:8080",
                "--mount",
                f"type=bind,src={ROOT / 'apps/web/dist'},dst=/usr/share/nginx/html,readonly",
                "--mount",
                f"type=bind,src={config},dst=/etc/nginx/conf.d/default.conf,readonly",
                "nginx:alpine",
            ],
            environment,
        )
        with local_client() as client:
            wait_ready(lambda: client.get(web_url).status_code == 200, "Web")
        run(
            [
                "uv",
                "run",
                "--frozen",
                "--package",
                "knicksiq-api",
                "python",
                "tools/release/readiness.py",
                "--base-url",
                api_url,
                "--local-https-proxy",
                "--bundle",
                BUNDLE,
                "--sha256",
                BUNDLE_SHA256,
                "--output",
                str(output / "api-smoke.json"),
            ],
            environment,
        )
        run(
            [
                "pnpm",
                "exec",
                "playwright",
                "test",
                "e2e/production-live.spec.ts",
                "--workers=1",
                "--reporter=json",
                "--output",
                str(output / "browser-artifacts"),
            ],
            {**environment, "KNICKSIQ_LIVE_REDIS_CONTAINER": names["redis"]},
            ROOT / "apps/web",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-base", type=int, default=19430)
    parser.add_argument(
        "--output", type=Path, default=Path("release-artifacts/production-completion")
    )
    args = parser.parse_args()
    if not 1024 <= args.port_base <= 65532:
        parser.error("port-base must leave four unprivileged TCP ports")
    identity = uuid.uuid4().hex[:10]
    output = (ROOT / args.output / f"run-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{identity}").resolve()
    output.mkdir(parents=True)
    ports = {
        name: args.port_base + index for index, name in enumerate(("pg", "redis", "api", "web"))
    }
    names = {name: f"kiq-e2e-{identity}-{name}" for name in ("pg", "redis", "web")}
    api_url = f"http://127.0.0.1:{ports['api']}"
    web_url = f"http://127.0.0.1:{ports['web']}"
    verdict = {
        "scope": (
            "Local isolated unsampled-shadow API and built browser. "
            "No provider quality or launch approval."
        ),
        "passed": False,
    }
    inherited = inherited_environment()
    try:
        endpoint = local_daemon_endpoint(inherited)
        verdict["daemon"] = {
            "kind": "unix-socket" if endpoint.startswith("unix://") else "loopback-tcp"
        }
        environment = scenario_environment(
            inherited, endpoint, identity, ports, api_url, web_url, output
        )
        ensure_ports_free(ports)
    except Exception as exc:
        verdict["error"] = {"type": type(exc).__name__, "message": redact(str(exc))}
        wrote = write_verdict(output, verdict)
        print(
            f"Aborted before allocating resources: {verdict['error']['message']}",
            file=sys.stderr,
        )
        announce(output)
        return 0 if verdict["passed"] and wrote else 1
    state: dict = {"containers": [], "api": None, "cleaning": False}
    previous = install_handlers(state)
    wrote = False
    try:
        try:
            run_scenario(state, environment, ports, names, api_url, web_url, output)
            verdict["passed"] = True
        except DriverInterrupted as exc:
            verdict["error"] = {"type": "Interrupted", "message": redact(str(exc))}
        except KeyboardInterrupt:
            verdict["error"] = {"type": "Interrupted", "message": "keyboard interrupt"}
        except Exception as exc:
            traceback.print_exc()
            verdict["error"] = {"type": type(exc).__name__, "message": redact(str(exc))}
    finally:
        state["cleaning"] = True
        try:
            failures = teardown(state, environment)
        except Exception as exc:  # noqa: BLE001 - the verdict must still be written
            failures = [{"resource": "teardown", "error": redact(f"{type(exc).__name__}: {exc}")}]
        if failures:
            verdict["cleanup_failures"] = failures
            verdict["passed"] = False
        wrote = write_verdict(output, verdict)
        restore_handlers(previous)
        announce(output)
    return 0 if verdict["passed"] and wrote else 1


if __name__ == "__main__":
    raise SystemExit(main())
