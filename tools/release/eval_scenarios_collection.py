"""Collection scenarios: the disabled profile and outbound guards.

The service profile's guard proof, run stamp and attestation live in
``eval_scenarios_service``; the attempt cap lives in ``eval_scenarios_budget``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from eval_scenario_fixtures import dump, load, synthetic_mapping, write_dataset
from eval_scenario_support import clean_env, expect, metric, run_cli


class FakeAPI(BaseHTTPRequestHandler):
    """A local candidate API stand-in that records every request body it receives."""

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.requests.append(body)  # type: ignore[attr-defined]
        request_id = body["request_id"]
        snapshot = {
            "revision": body["expected_revision"] + 1,
            "exchanges": [
                {
                    "id": request_id,
                    "message": body["message"],
                    "reply": {"id": request_id, "text": "Synthetic.", "status": "complete"},
                }
            ],
        }
        encoded = (
            "event: settled\ndata: "
            + json.dumps({"request_id": request_id, "snapshot": snapshot})
            + "\n\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        return


@contextmanager
def fake_api(handler: type[FakeAPI] = FakeAPI) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.requests = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server.requests  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()


def collect_args(
    base_url: str,
    questions: Path,
    expectations: Path,
    responses: Path,
    *extra: str,
) -> list[str]:
    return [
        "collect",
        "--questions",
        str(questions),
        "--expectations",
        str(expectations),
        "--base-url",
        base_url,
        "--responses",
        str(responses),
        *extra,
    ]


def scenario_collect_profile(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    with fake_api() as (base_url, requests_seen):
        responses = directory / "collected.jsonl"
        result = run_cli(
            collect_args(
                base_url,
                questions_path,
                expectations_path,
                responses,
                "--profile",
                "disabled",
                "--limit",
                "3",
            ),
            cwd=directory,
        )
        expect(result.returncode == 0, f"collect failed: {result.stderr[-1200:]}", problems)
        if responses.exists():
            rows = [json.loads(line) for line in responses.read_text().splitlines() if line.strip()]
            expect(len(rows) == 3, "collect writes one record per requested case", problems)
            expect(
                all(
                    row["request_id"] and row["request"]["request_id"] == row["request_id"]
                    for row in rows
                ),
                "collect sends a turn id and records it",
                problems,
            )
            expect(
                len(requests_seen) == 3
                and all("request_id" in request for request in requests_seen),
                "server sees turn ids",
                problems,
            )
            expect(
                all(row["response"]["status"] == "complete" for row in rows),
                "collect records the runtime outcome untouched",
                problems,
            )
        else:
            problems.append("collect wrote no responses")
        scored = directory / "collect-report.json"
        result = run_cli(
            [
                "score",
                "--questions",
                str(questions_path),
                "--expectations",
                str(expectations_path),
                "--mapping",
                str(mapping),
                "--responses",
                str(responses),
                "--output",
                str(scored),
            ],
            cwd=directory,
        )
        expect(result.returncode == 0, f"score failed: {result.stderr[-1200:]}", problems)
        report = load(scored) if scored.exists() else None
        if report is not None:
            expect(
                metric(report, "disposition_accuracy")["denominator"] == 120,
                "partial collection still scores the fixed 120 denominator",
                problems,
            )
            expect(
                report["profile"]["provider_requests"] is None,
                "public replies cannot measure private provider activity",
                problems,
            )
    return problems


def scenario_collect_ignores_ambient_proxy(directory: Path) -> list[str]:
    """An ambient proxy must never be used for the local candidate."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    env = clean_env()
    env.update(
        {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
            "NO_PROXY": "",
            "no_proxy": "",
        }
    )
    responses = directory / "collected.jsonl"
    with fake_api() as (base_url, requests_seen):
        result = run_cli(
            collect_args(
                base_url,
                questions_path,
                expectations_path,
                responses,
                "--profile",
                "disabled",
                "--limit",
                "2",
            ),
            cwd=directory,
            env=env,
        )
        expect(
            result.returncode == 0,
            f"a dead proxy must not intercept the local candidate: {result.stderr[-800:]}",
            problems,
        )
        expect(len(requests_seen) == 2, "the local candidate receives both requests", problems)
    return problems


def scenario_collect_rejects_remote_base_url(directory: Path) -> list[str]:
    """The disabled collector is loopback-only, so it cannot emit outbound traffic."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    responses = directory / "collected.jsonl"
    result = run_cli(
        collect_args(
            "http://192.0.2.10:8000",
            questions_path,
            expectations_path,
            responses,
            "--profile",
            "disabled",
            "--limit",
            "1",
        ),
        cwd=directory,
    )
    expect(result.returncode != 0, "a non-loopback candidate must be refused", problems)
    expect(
        "loopback" in result.stderr.lower(), "the refusal names the loopback requirement", problems
    )
    expect(not responses.exists(), "a refused candidate writes no responses", problems)
    return problems


def scenario_collect_disabled_flag_only(directory: Path) -> list[str]:
    """A run configuration cannot dress a disabled run up as paid."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    config = dump(directory / "run-config.json", {"schema": "evaluation-run-config-v1"})
    responses = directory / "collected.jsonl"
    with fake_api() as (base_url, requests_seen):
        result = run_cli(
            collect_args(
                base_url,
                questions_path,
                expectations_path,
                responses,
                "--run-config",
                str(config),
                "--run-config-sha256",
                "c" * 64,
                "--limit",
                "1",
            ),
            cwd=directory,
        )
        expect(
            result.returncode != 0,
            "a run configuration must not attach to the disabled profile",
            problems,
        )
        expect("service" in result.stderr.lower(), f"{result.stderr[-400:]}", problems)
        expect(requests_seen == [], "no request is made for the mislabelled profile", problems)
    return problems
