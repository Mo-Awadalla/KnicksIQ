"""Verify the public request and telemetry boundary locally.

This drives the real ASGI application stack but never a provider, remote data
store, or Sentry: DSNs, Redis, and provider keys are removed from the
environment before the app is imported, and request bodies are synthesized in
process. Failing cases in this file are the reproduced findings recorded in
release-artifacts/production-readiness-20261030/failure-probes.json:

* ``oversized_body.rejected_with_413`` was false — a 1,048,652-byte JSON body
  reached the route.
* ``exception_logging.synthetic_prompt_in_structured_log`` was true — the
  structlog exception payload carried traceback locals.
* ``session_privacy`` recorded the retention wording the privacy page must
  describe instead of denying.

Run with the repository virtualenv::

    .venv/bin/python tools/release/privacy_boundary_check.py

Exit code 0 means every check passed. ``--output`` writes the same report.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps/api"

MARKER = "SYNTHETIC-PROMPT-9f3c1a"

os.environ.update(
    {
        "TEST_MODE": "true",
        "ENVIRONMENT": "development",
        "DEBUG": "false",
        "LOG_JSON": "true",
        "LOG_LEVEL": "INFO",
        "AI_PROVIDER": "mock",
        "ANALYSIS_ANSWER_MODE": "deterministic",
        "ANALYST_EVIDENCE_LOOP_ENABLED": "false",
        "RAG_QDRANT_ENABLED": "false",
        "REQUIRE_ACTIVE_RELEASE": "false",
    }
)
for _secret in (
    "SENTRY_DSN",
    "REDIS_URL",
    "OPENROUTER_API_KEY",
    "AI_API_KEY",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "ADMIN_API_KEY",
):
    os.environ.pop(_secret, None)

sys.path.insert(0, str(API_ROOT))

from app.core.config import Settings  # noqa: E402

# A developer .env carries live provider keys and a Sentry DSN. Nothing in this
# verifier may inherit it.
Settings.model_config["env_file"] = None

import structlog  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.core.public_boundary import (  # noqa: E402
    MAX_REQUEST_BYTES,
    RequestBodyLimitMiddleware,
    scrub_sentry_event,
)

CHECKS: list[dict[str, Any]] = []


def verify(
    name: str,
    passed: bool,
    evidence: object,
    *,
    kind: str = "behavior",
) -> None:
    CHECKS.append({"name": name, "kind": kind, "passed": bool(passed), "evidence": evidence})


def build_app() -> tuple[Any, str]:
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    if not any(item.cls is RequestBodyLimitMiddleware for item in app.user_middleware):
        raise RuntimeError("The application does not enforce the public body boundary")
    return app, "create_app"


def make_scope(
    *,
    method: str = "POST",
    path: str = "/analysis/query",
    headers: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            *((key.lower().encode(), value.encode()) for key, value in (headers or [])),
        ],
        "client": ("127.0.0.1", 43110),
        "server": ("testserver", 80),
    }


def body_messages(payload: bytes, chunk_size: int = 65536) -> deque[dict[str, Any]]:
    chunks = [payload[index : index + chunk_size] for index in range(0, len(payload), chunk_size)]
    if not chunks:
        chunks = [b""]
    return deque(
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    )


async def drive(
    app: Any,
    *,
    scope: dict[str, Any],
    messages: deque[dict[str, Any]],
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        if messages:
            return messages.popleft()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await asyncio.wait_for(app(scope, receive, send), timeout=20)
    return sent


def read_response(sent: list[dict[str, Any]]) -> tuple[int, dict[str, bytes], Any, bytes]:
    start = next(item for item in sent if item["type"] == "http.response.start")
    raw = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    headers = {key.lower(): value for key, value in start["headers"]}
    try:
        payload = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        payload = None
    return start["status"], headers, payload, raw


async def check_envelope(app: Any) -> None:
    request_id = "verify-declared-length"
    oversized = b" " * (1024 * 1024 + 396)
    scope = make_scope(
        headers=[
            ("content-type", "application/json"),
            ("content-length", str(len(oversized))),
            ("x-request-id", request_id),
        ]
    )
    sent = await drive(app, scope=scope, messages=body_messages(oversized))
    status, headers, payload, _ = read_response(sent)
    envelope_ok = (
        status == 413
        and isinstance(payload, dict)
        and payload.get("error", {}).get("code") == "request_too_large"
        and payload.get("request_id") == request_id
        and headers.get(b"x-request-id", b"").decode() == request_id
        and headers.get(b"content-type") == b"application/json"
    )
    verify(
        "declared_length_rejected_before_parsing",
        envelope_ok,
        {
            "request_bytes": len(oversized),
            "status": status,
            "body": payload,
            "x_request_id": headers.get(b"x-request-id", b"").decode(),
            "server_timing_present": b"server-timing" in headers,
        },
    )
    verify(
        "rejection_runs_inside_request_middleware",
        b"server-timing" in headers and b"x-frame-options" in headers,
        {"headers": sorted(key.decode() for key in headers)},
    )


async def check_chunked_stream(app: Any) -> None:
    oversized = b"x" * (MAX_REQUEST_BYTES + 1)
    scope = make_scope(
        headers=[
            ("content-type", "application/json"),
            ("transfer-encoding", "chunked"),
            ("x-request-id", "verify-chunked"),
        ]
    )
    sent = await drive(app, scope=scope, messages=body_messages(oversized, chunk_size=65536))
    status, headers, payload, _ = read_response(sent)
    verify(
        "chunked_stream_over_cap_rejected",
        status == 413
        and isinstance(payload, dict)
        and payload.get("error", {}).get("code") == "request_too_large"
        and headers.get(b"connection") == b"close",
        {"status": status, "sent_chunks": 3, "body": payload},
    )


async def check_false_length(app: Any) -> None:
    over = b"y" * (MAX_REQUEST_BYTES + 1)
    scope = make_scope(
        headers=[
            ("content-type", "application/json"),
            ("content-length", "100"),
            ("x-request-id", "verify-false-length"),
        ]
    )
    sent = await drive(app, scope=scope, messages=body_messages(over))
    status, _, payload, _ = read_response(sent)
    verify(
        "underreported_length_rejected",
        status == 413
        and isinstance(payload, dict)
        and payload["error"]["code"] == "request_too_large",
        {"declared_length": 100, "actual_bytes": len(over), "status": status},
    )


async def check_exact_cap_boundary(app: Any) -> None:
    exact = b'{"question":"' + b"z" * (MAX_REQUEST_BYTES - 15) + b'"}'
    scope = make_scope(
        headers=[
            ("content-type", "application/json"),
            ("content-length", str(len(exact))),
            ("x-request-id", "verify-exact-cap"),
        ]
    )
    sent = await drive(app, scope=scope, messages=body_messages(exact))
    status, _, body, _ = read_response(sent)
    verify(
        "body_at_cap_reaches_validation",
        status == 422
        and isinstance(body, dict)
        and body.get("error", {}).get("code") == "invalid_request",
        {"request_bytes": len(exact), "status": status, "body": body},
    )


async def check_empty_body(app: Any) -> None:
    scope = make_scope(
        headers=[("content-type", "application/json"), ("x-request-id", "verify-empty")],
    )
    sent = await drive(app, scope=scope, messages=body_messages(b""))
    status, _, body, _ = read_response(sent)
    verify(
        "empty_body_answered_without_hanging",
        status == 422
        and isinstance(body, dict)
        and body.get("error", {}).get("code") == "invalid_request",
        {"status": status, "body": body},
    )


async def check_disconnect(app: Any) -> None:
    scope = make_scope(
        headers=[("content-type", "application/json"), ("x-request-id", "verify-gone")]
    )
    sent = await drive(
        app,
        scope=scope,
        messages=deque([{"type": "http.disconnect"}]),
    )
    status, _, body, _ = read_response(sent)
    verify(
        "disconnect_answered_without_deadlock",
        status == 400
        and isinstance(body, dict)
        and body.get("error", {}).get("code") == "request_incomplete",
        {"status": status, "body": body},
    )


async def check_stalled_upload() -> None:
    async def downstream(scope: dict[str, Any], receive: Any, send: Any) -> None:
        raise AssertionError("A stalled body reached application parsing")

    async def slow_receive() -> dict[str, Any]:
        await asyncio.sleep(2)
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await RequestBodyLimitMiddleware(downstream, read_timeout=0.05)(
        make_scope(headers=[("content-length", "10")]), slow_receive, send
    )
    status, headers, body, _ = read_response(sent)
    verify(
        "stalled_body_times_out_bounded",
        status == 408
        and isinstance(body, dict)
        and body.get("error", {}).get("code") == "request_timeout"
        and headers.get(b"connection") == b"close",
        {"status": status},
    )


def check_sentry_scrub() -> None:
    event = {
        "type": "error",
        "transaction": "GET /analysis/query?question=SECRET-QUERY",
        "user": {"id": "anon"},
        "request": {
            "url": "http://test/analysis/query?question=SECRET-QUERY",
            "query_string": "question=SECRET-QUERY",
            "data": {"question": "SECRET-BODY"},
            "headers": {"Authorization": "Bearer SECRET-TOKEN"},
            "cookies": "session=SECRET-COOKIE",
            "env": {"REMOTE_ADDR": "203.0.113.9"},
        },
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": "prompt SECRET-QUERY failed",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "app/api/analysis.py",
                                "function": "query_analysis",
                                "lineno": 42,
                                "vars": {"question": "SECRET-QUERY", "req": "SECRET-BODY"},
                            }
                        ]
                    },
                }
            ]
        },
        "threads": {"values": [{"stacktrace": {"frames": [{"vars": {"prompt": "SECRET-QUERY"}}]}}]},
        "breadcrumbs": {
            "values": [
                {
                    "category": "http",
                    "message": "POST /analysis/query?question=SECRET-QUERY",
                    "data": {"url": "http://test/analysis/query?question=SECRET-QUERY"},
                }
            ]
        },
        "spans": [
            {
                "op": "http.client",
                "description": "POST /analysis/query?question=SECRET-QUERY",
                "data": {
                    "url": "https://provider.example/chat?key=SECRET-TOKEN",
                    "http.query": "question=SECRET-QUERY",
                    "db.statement": "SELECT * FROM game WHERE note = 'SECRET-QUERY'",
                    "db.params": ["SECRET-QUERY"],
                },
            }
        ],
    }
    scrubbed = scrub_sentry_event(dict(event), None)
    serialized = json.dumps(scrubbed, sort_keys=True)
    token_count = serialized.count("SECRET-")
    frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
    verify(
        "sentry_event_has_no_user_content",
        token_count == 0
        and "vars" not in frame
        and scrubbed["exception"]["values"][0]["value"] == "<redacted>"
        and scrubbed["exception"]["values"][0]["type"] == "RuntimeError"
        and "query_string" not in scrubbed["request"]
        and "data" not in scrubbed["request"]
        and "headers" not in scrubbed["request"]
        and "cookies" not in scrubbed["request"]
        and "env" not in scrubbed["request"]
        and scrubbed["request"]["url"] == "http://test/analysis/query"
        and "user" not in scrubbed
        and "data" not in scrubbed["breadcrumbs"]["values"][0]
        and "message" not in scrubbed["breadcrumbs"]["values"][0]
        and scrubbed["spans"][0]["description"] == "POST /analysis/query"
        and scrubbed["spans"][0]["data"] == {}
        and scrubbed["transaction"] == "GET /analysis/query",
        {"leaked_markers": token_count, "frame": frame, "span": scrubbed["spans"][0]},
    )


def _logged_exception(log_json: bool, debug: bool) -> str:
    os.environ["LOG_JSON"] = "true" if log_json else "false"
    os.environ["DEBUG"] = "true" if debug else "false"
    from app.core.config import get_settings

    get_settings.cache_clear()
    structlog.reset_defaults()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        configure_logging()
        logger = get_logger("verify.boundary")

        def handle_request() -> None:
            question = MARKER
            raise RuntimeError(f"provider rejected prompt {question}")

        try:
            handle_request()
        except RuntimeError:
            logger.exception("verify.exception")
    return buffer.getvalue()


def check_logging_redaction() -> None:
    captured = _logged_exception(log_json=True, debug=False)
    record: dict[str, Any] | None = None
    for line in captured.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if candidate.get("event") == "verify.exception":
            record = candidate
    stack = (record or {}).get("exception", [{}])[0]
    verify(
        "json_exception_excludes_locals_and_message",
        record is not None
        and MARKER not in captured
        and '"locals"' not in captured
        and stack.get("exc_type") == "RuntimeError"
        and stack.get("exc_value") == "<redacted>"
        and isinstance(stack.get("exc_value_digest"), str),
        {
            "record_keys": sorted(record or {}),
            "exception_type": stack.get("exc_type"),
            "exception_value": stack.get("exc_value"),
            "frames": [
                {"name": frame["name"], "lineno": frame["lineno"]}
                for frame in stack.get("frames", [])
            ],
        },
    )

    console = _logged_exception(log_json=False, debug=True)
    verify(
        "console_exception_excludes_message",
        MARKER not in console and "RuntimeError: <redacted>" in console,
        {"console_bytes": len(console), "redacted_line": "RuntimeError: <redacted>" in console},
    )


def check_request_schema_bounds() -> None:
    """The public request model must accept a whole-season scope.

    ``resolve_query`` stores every filtered game id in the conversation state,
    and the archive has 101 games, so the state bound has to clear the public
    list cap of 200 without allowing unbounded lists.
    """
    from app.api.analysis_models import AnalysisQueryRequest
    from pydantic import ValidationError

    base = {
        "question": "Who scored the most points?",
        "season": "2025-26",
        "context": [],
        "conversation_state": {"game_ids": list(range(200))},
    }
    accepted = AnalysisQueryRequest.model_validate(base)
    state = accepted.conversation_state
    accepted_ids = len(state.game_ids) if state is not None else 0
    over = dict(base, conversation_state={"game_ids": list(range(201))})
    unknown = dict(base, unexpected_field=True)
    rejected_over = rejected_unknown = False
    try:
        AnalysisQueryRequest.model_validate(over)
    except ValidationError:
        rejected_over = True
    try:
        AnalysisQueryRequest.model_validate(unknown)
    except ValidationError:
        rejected_unknown = True
    verify(
        "request_schema_bounds_whole_season_scope",
        accepted.season == "2025-26" and accepted_ids == 200 and rejected_over and rejected_unknown,
        {
            "accepted_game_ids": accepted_ids,
            "rejected_201": rejected_over,
            "rejected_unknown_field": rejected_unknown,
        },
    )


def base_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


async def run() -> dict[str, Any]:
    app, integration_mode = build_app()
    await check_envelope(app)
    await check_chunked_stream(app)
    await check_false_length(app)
    await check_exact_cap_boundary(app)
    await check_empty_body(app)
    await check_disconnect(app)
    await check_stalled_upload()
    check_sentry_scrub()
    check_logging_redaction()
    check_request_schema_bounds()
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "scope": (
            "In-process ASGI checks of the actual public body boundary, Sentry scrubbing, "
            "exception redaction, and request validation. No provider, Redis, Sentry "
            "DSN, or remote write is used. This is not deployment or release approval."
        ),
        "base_commit": base_commit(),
        "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "integration_mode": integration_mode,
        "max_request_bytes": MAX_REQUEST_BYTES,
        "checks": CHECKS,
        "passed": all(check["passed"] for check in CHECKS),
        "passed_count": sum(check["passed"] for check in CHECKS),
        "check_count": len(CHECKS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = asyncio.run(run())
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
