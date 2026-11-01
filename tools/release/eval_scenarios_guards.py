"""Guards around the standalone evaluation driver: DB scope, proxy, process and evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from eval_scenario_support import REPO, clean_env, expect, load

TOOLS = REPO / "tools/release"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import eval_runner  # noqa: E402  (path above is the driver under test)


class ReadyServer(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"status": "ready"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        return


def runner_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOLS / "eval_runner.py"), *args],
        cwd=REPO,
        env=clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def scenario_runner_rejects_remote_db(directory: Path) -> list[str]:
    """A remote DSN is refused before the API is started, so no remote write is possible."""
    problems: list[str] = []
    output = directory / "run"
    result = runner_cli(
        [
            "--db-url",
            "postgresql+asyncpg://knicksiq:knicksiq@db.example.com:5432/knicksiq",
            "--output",
            str(output),
        ]
    )
    expect(result.returncode != 0, "a remote DSN must be refused", problems)
    expect("loopback" in result.stderr.lower(), "the refusal names the loopback rule", problems)
    expect(not (output / "run-summary.json").exists(), "no evidence claims a refused run", problems)
    expect(not (output / "api.log").exists(), "the API was never started", problems)
    return problems


def scenario_runner_db_url_matrix(directory: Path) -> list[str]:
    """Only loopback PostgreSQL DSNs reach the API; everything else is refused."""
    problems: list[str] = []
    accepted = [
        "postgresql+asyncpg://knicksiq:knicksiq@127.0.0.1:55432/knicksiq",
        "postgresql://knicksiq@localhost:5432/knicksiq",
        "postgresql+asyncpg://knicksiq:knicksiq@[::1]:5432/knicksiq",
    ]
    for url in accepted:
        try:
            eval_runner.validate_db_url(url)
        except eval_runner.RunnerFailure as exc:
            problems.append(f"{url} must be accepted: {exc}")
    refused = [
        "postgresql+asyncpg://knicksiq:knicksiq@db.example.com:5432/knicksiq",
        "postgresql+asyncpg://knicksiq:knicksiq@10.0.0.5:5432/knicksiq",
        "postgresql:///knicksiq",
        "mysql://root@127.0.0.1:3306/knicksiq",
        "postgresql+asyncpg://knicksiq:knicksiq@127.0.0.1:5432/knicksiq?host=db.example.com",
    ]
    for url in refused:
        try:
            eval_runner.validate_db_url(url)
        except eval_runner.RunnerFailure:
            continue
        problems.append(f"{url} must be refused")
    return problems


def scenario_runner_readiness_ignores_proxy(directory: Path) -> list[str]:
    """Readiness must reach the local child directly, never through an ambient proxy."""
    problems: list[str] = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ReadyServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    previous = {
        key: os.environ.get(key)
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "no_proxy")
    }
    try:
        os.environ.update(
            {
                "HTTP_PROXY": "http://127.0.0.1:1",
                "HTTPS_PROXY": "http://127.0.0.1:1",
                "ALL_PROXY": "http://127.0.0.1:1",
            }
        )
        os.environ.pop("NO_PROXY", None)
        os.environ.pop("no_proxy", None)
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            body = eval_runner.wait_ready(base_url, child, time.monotonic() + 10)
        except eval_runner.RunnerFailure as exc:
            problems.append(f"a dead ambient proxy intercepted readiness: {exc}")
        else:
            expect(
                body.get("status") == "ready", "readiness reports the child's own status", problems
            )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        eval_runner.stop_process(child)
        server.shutdown()
        server.server_close()
    return problems


def scenario_runner_readiness_rejects_foreign_listener(directory: Path) -> list[str]:
    """A ready listener that is not the child cannot satisfy readiness."""
    problems: list[str] = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ReadyServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    child = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"], start_new_session=True)
    child.wait(timeout=10)
    try:
        try:
            eval_runner.wait_ready(
                f"http://127.0.0.1:{server.server_address[1]}", child, time.monotonic() + 3
            )
        except eval_runner.RunnerFailure as exc:
            expect("exited" in str(exc), "the failure names the child exit", problems)
        else:
            problems.append("a foreign listener satisfied readiness for a dead child")
    finally:
        server.shutdown()
        server.server_close()
    return problems


def scenario_runner_cleanup_escalates(directory: Path) -> list[str]:
    """A child that ignores SIGTERM is still stopped and the cleanup reports no leak."""
    problems: list[str] = []
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
        ],
        start_new_session=True,
    )
    time.sleep(0.3)
    started = time.monotonic()
    left = eval_runner.stop_process(child, grace=2.0)
    elapsed = time.monotonic() - started
    expect(child.poll() is not None, "the child is gone after cleanup", problems)
    expect(elapsed < 10, f"cleanup is bounded, took {elapsed:.1f}s", problems)
    expect(left == [], f"cleanup reports no residue: {left}", problems)
    return problems


def scenario_runner_failed_startup_preserves_evidence(directory: Path) -> list[str]:
    """A failed startup still writes relative evidence and reaps the child."""
    problems: list[str] = []
    output = directory / "run"
    result = runner_cli(
        [
            "--db-url",
            "postgresql+asyncpg://knicksiq:knicksiq@127.0.0.1:1/knicksiq",
            "--output",
            str(output),
            "--startup-seconds",
            "12",
        ]
    )
    expect(result.returncode != 0, "an unreachable local database cannot produce a run", problems)
    summary_path = output / "run-summary.json"
    if not summary_path.exists():
        return problems + ["a failed startup must still write run-summary.json"]
    summary = load(summary_path)
    expect(summary.get("status") == "failed", "the evidence is marked failed", problems)
    expect("error" in summary, "the failure reason is recorded", problems)
    artifacts = summary.get("artifacts") or {}
    expect(bool(artifacts), "artifact paths are recorded", problems)
    for name, value in artifacts.items():
        expect(
            not str(value).startswith("/"),
            f"artifact {name} is relative, not {value}",
            problems,
        )
    expect(
        all("secret" not in str(value) for value in artifacts.values()),
        "no DSN leaks into the artifact paths",
        problems,
    )
    expect((output / "api.log").exists(), "the child log survives the failure", problems)
    expect(
        summary.get("cleanup_failures", []) == [],
        f"cleanup reported no residue: {summary.get('cleanup_failures')}",
        problems,
    )
    return problems
