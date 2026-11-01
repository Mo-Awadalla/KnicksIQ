"""Verify the Sentry envelopes the application sends carry no user content.

The actual ``app.main`` application runs over ASGI and the real ``sentry_sdk``
builds, scrubs, and serializes the envelopes. This verifier injects only an
in-memory transport and a marker counter wrapped around the ``before_send`` and
``before_send_transaction`` callables the application itself registers. A
callback the app forgot to register therefore shows up as a leaked marker
instead of being supplied here.

A temporary probe route raises ``RuntimeError`` with a marker in the message
while the request carries markers in its query string and JSON body. One SDK
transaction is sampled explicitly around that request so the transaction
callback runs without touching the application's sampling options. Envelope
bytes are inspected only in memory; report fields are names, paths, and counts.

Run with the repository virtualenv::

    .venv/bin/python tools/release/telemetry_sdk_check.py

Exit code 0 means every check passed. ``--output`` writes the report.
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
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps/api"

PROBE_PATH = "/__telemetry-check__/raise"
MARKER_QUERY = "SYNTHETIC-TELEMETRY-QUERY-9f3c1a"
MARKER_BODY = "SYNTHETIC-TELEMETRY-BODY-9f3c1a"
MARKER_TRANSACTION = "SYNTHETIC-TELEMETRY-TRANSACTION-9f3c1a"
MARKERS = (MARKER_QUERY, MARKER_BODY, MARKER_TRANSACTION)

DUMMY_DSN = "http://public@127.0.0.1:1/1"

# A developer .env holds live provider keys and a real Sentry DSN, so the
# environment is set explicitly here and `.env` loading is switched off below.
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
        "SENTRY_DSN": DUMMY_DSN,
        "SENTRY_RELEASE": "telemetry-sdk-check",
    }
)
for _secret in (
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
from fastapi import Request  # noqa: E402

Settings.model_config["env_file"] = None

import sentry_sdk  # noqa: E402
from sentry_sdk.transport import Transport  # noqa: E402

CHECKS: list[dict[str, Any]] = []


class RecordingTransport(Transport):
    """In-memory destination that keeps the exact bytes the SDK would send."""

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        self.wire: list[bytes] = []

    def capture_envelope(self, envelope: Any) -> None:
        self.wire.append(envelope.serialize())


TRANSPORT = RecordingTransport()
PRE_SCRUB: dict[str, list[list[str]]] = {"error": [], "transaction": []}
_CAPTURE = io.StringIO()


def verify(name: str, passed: bool, evidence: object) -> None:
    CHECKS.append({"name": name, "kind": "behavior", "passed": bool(passed), "evidence": evidence})


def marker_paths(value: Any) -> list[str]:
    """JSON-pointer paths holding a synthetic marker, never the values."""
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                walk(child, f"{path}/{key}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}/{index}")
        elif isinstance(node, str) and any(marker in node for marker in MARKERS):
            found.append(path or "/")

    walk(value, "")
    return found


def marker_occurrences(payload: bytes) -> int:
    return sum(payload.count(marker.encode()) for marker in MARKERS)


def spy_on(kind: str, callback: Any) -> Any:
    def instrumented(event: Any, hint: Any = None) -> Any:
        PRE_SCRUB[kind].append(marker_paths(event))
        return callback(event, hint)

    return instrumented


_real_init = sentry_sdk.init


def instrumented_init(*args: Any, **kwargs: Any) -> Any:
    """Observe raw markers before the application's own scrubbers run."""
    for name, kind in (("before_send", "error"), ("before_send_transaction", "transaction")):
        callback = kwargs.get(name)
        if callable(callback):
            kwargs[name] = spy_on(kind, callback)
    if "transport" in kwargs:
        raise RuntimeError("The application must not configure its own telemetry transport")
    kwargs["transport"] = TRANSPORT
    return _real_init(*args, **kwargs)


sentry_sdk.init = instrumented_init


def build_app() -> Any:
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()

    @app.post(PROBE_PATH)
    async def telemetry_probe(request: Request):
        raw = await request.body()
        try:
            parsed = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            parsed = {}
        submitted = parsed.get("question", "") if isinstance(parsed, dict) else ""
        raise RuntimeError(
            f"telemetry probe failed question={request.query_params.get('question')} "
            f"body={submitted}"
        )

    return app


def probe_scope(body: bytes) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": PROBE_PATH,
        "raw_path": PROBE_PATH.encode(),
        "query_string": f"question={MARKER_QUERY}".encode(),
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 43110),
        "server": ("testserver", 80),
    }


async def drive_request(app: Any, body: bytes) -> tuple[int, dict[bytes, bytes], bytes, str | None]:
    messages = deque([{"type": "http.request", "body": body, "more_body": False}])
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return messages.popleft() if messages else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    raised: str | None = None
    transaction_name = f"{PROBE_PATH}?probe={MARKER_TRANSACTION}"
    with sentry_sdk.start_transaction(name=transaction_name, op="telemetry.check", sampled=True):
        try:
            await asyncio.wait_for(app(probe_scope(body), receive, send), timeout=20)
        except RuntimeError as exc:
            raised = type(exc).__name__
    start = next(item for item in sent if item["type"] == "http.response.start")
    raw = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return start["status"], {key.lower(): value for key, value in start["headers"]}, raw, raised


def split_envelope(raw: bytes) -> tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]:
    tokens = [line for line in raw.split(b"\n") if line.strip()]
    header = json.loads(tokens[0])
    items: list[tuple[dict[str, Any], Any]] = []
    index = 1
    while index < len(tokens):
        item_header = json.loads(tokens[index])
        payload: Any = None
        if index + 1 < len(tokens):
            try:
                payload = json.loads(tokens[index + 1])
            except json.JSONDecodeError:
                payload = None
        items.append((item_header, payload))
        index += 2
    return header, items


def log_records(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            records.append(candidate)
    return records


def find_record(records: list[dict[str, Any]], event: str) -> dict[str, Any] | None:
    for record in records:
        if record.get("event") == event:
            return record
    return None


def check_init() -> None:
    client = sentry_sdk.get_client()
    dsn = urlsplit(client.dsn or "")
    dsn_host = f"{dsn.hostname}:{dsn.port}"
    verify(
        "transport_is_in_memory_only",
        isinstance(client.transport, RecordingTransport)
        and client.transport is TRANSPORT
        and dsn_host == "127.0.0.1:1",
        {
            "client_transport": type(client.transport).__name__,
            "dsn_host": dsn_host,
            "network_calls": "none",
        },
    )


def check_coverage(events: list[tuple[dict[str, Any], Any]]) -> dict[str, Any]:
    error_paths = [path for paths in PRE_SCRUB["error"] for path in paths]
    transaction_paths = [path for paths in PRE_SCRUB["transaction"] for path in paths]
    types = [item_header.get("type") for item_header, _ in events]
    verify(
        "sdk_produced_both_envelope_kinds",
        "event" in types and "transaction" in types,
        {"item_types": types},
    )
    verify(
        "raw_markers_reached_callbacks_before_scrub",
        bool(error_paths) and bool(transaction_paths),
        {
            "error_event_paths": sorted(set(error_paths)),
            "transaction_event_paths": sorted(set(transaction_paths)),
            "note": "absence after the transport only counts once a raw marker was seen here",
        },
    )
    return {
        "error_paths": sorted(set(error_paths)),
        "transaction_paths": sorted(set(transaction_paths)),
        "query_covered": any("/request/query_string" in path for path in error_paths),
        "sampling_context_covered": any(
            "dynamic_sampling_context" in path for path in transaction_paths
        ),
    }


def check_wire() -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    headers: list[dict[str, Any]] = []
    events: list[tuple[dict[str, Any], Any]] = []
    for raw in TRANSPORT.wire:
        envelope_header, items = split_envelope(raw)
        headers.append(envelope_header)
        events.extend(items)
    leaked = sum(marker_occurrences(raw) for raw in TRANSPORT.wire)
    verify(
        "wire_envelopes_exclude_all_markers",
        leaked == 0,
        {
            "envelope_count": len(TRANSPORT.wire),
            "envelope_bytes": sum(len(raw) for raw in TRANSPORT.wire),
            "marker_occurrences": leaked,
        },
    )
    return headers, events, leaked


def check_envelope_headers(headers: list[dict[str, Any]], coverage: dict[str, Any]) -> None:
    queried = [
        header["trace"]["transaction"]
        for header in headers
        if isinstance(header.get("trace"), dict)
        and isinstance(header["trace"].get("transaction"), str)
        and "?" in header["trace"]["transaction"]
    ]
    verify(
        "envelope_headers_carry_no_query_string",
        not queried
        and all(marker_occurrences(json.dumps(header).encode()) == 0 for header in headers),
        {
            "trace_headers_with_query": len(queried),
            "sampling_context_reached_callback": coverage["sampling_context_covered"],
            "note": "the SDK moves the sampling context into the envelope header",
        },
    )


def check_error_event(events: list[tuple[dict[str, Any], Any]], coverage: dict[str, Any]) -> None:
    error_event = next(
        (payload for item_header, payload in events if item_header.get("type") == "event"),
        None,
    )
    values = ((error_event or {}).get("exception") or {}).get("values") or []
    value = values[0] if values else {}
    frames = ((value.get("stacktrace") or {}).get("frames")) or []
    request = (error_event or {}).get("request") or {}
    request_text = json.dumps(request)
    verify(
        "exception_value_redacted",
        bool(values) and value.get("type") == "RuntimeError" and value.get("value") == "<redacted>",
        {
            "exception_type": value.get("type"),
            "exception_value": value.get("value"),
            "frame_count": len(frames),
        },
    )
    verify(
        "stack_frames_exclude_variables",
        bool(frames) and all("vars" not in frame and "locals" not in frame for frame in frames),
        {
            "frame_count": len(frames),
            "frames_with_vars": sum("vars" in frame for frame in frames),
        },
    )
    verify(
        "request_carries_no_query_or_body",
        not {"query_string", "data", "headers", "cookies", "env"} & set(request)
        and marker_occurrences(request_text.encode()) == 0
        and (not coverage["query_covered"] or bool(request.get("url")))
        and "?" not in str(request.get("url", "")),
        {
            "request_fields": sorted(request),
            "query_reached_callback": coverage["query_covered"],
            "url_has_query": "?" in str(request.get("url", "")),
            "marker_occurrences": marker_occurrences(request_text.encode()),
        },
    )


def check_public_response(
    status: int, headers: dict[bytes, bytes], raw: bytes, raised: str | None
) -> str | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    body = payload if isinstance(payload, dict) else {}
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    request_id = body.get("request_id")
    verify(
        "unhandled_error_reached_the_public_handler",
        raised == "RuntimeError" and status == 500,
        {
            "status": status,
            "raised": raised,
            "content_type": headers.get(b"content-type", b"").decode(),
        },
    )
    verify(
        "public_error_response_is_generic",
        error.get("code") == "internal_error"
        and error.get("message") == "Internal server error"
        and isinstance(request_id, str)
        and len(request_id) == 32
        and marker_occurrences(raw) == 0,
        {
            "status": status,
            "error_code": error.get("code"),
            "body_bytes": len(raw),
            "marker_occurrences": marker_occurrences(raw),
            "request_id_present": isinstance(request_id, str) and len(request_id) == 32,
        },
    )
    return request_id if isinstance(request_id, str) else None


def check_logs(text: str, request_id: str | None) -> None:
    records = log_records(text)
    starting = find_record(records, "knicksiq.api.starting")
    stopping = find_record(records, "knicksiq.api.stopping")
    unhandled = find_record(records, "knicksiq.api.unhandled")
    stack = ((unhandled or {}).get("exception") or [{}])[0]
    frames = stack.get("frames") or []
    verify(
        "lifespan_and_unhandled_logging_ran",
        starting is not None
        and stopping is not None
        and unhandled is not None
        and unhandled.get("request_id") == request_id,
        {
            "records": len(records),
            "lifespan_events": [
                name
                for name, record in (
                    ("knicksiq.api.starting", starting),
                    ("knicksiq.api.stopping", stopping),
                )
                if record is not None
            ],
            "unhandled_logged": unhandled is not None,
            "request_id_correlated": unhandled is not None
            and unhandled.get("request_id") == request_id,
        },
    )
    verify(
        "application_logs_exclude_markers_and_locals",
        marker_occurrences(text.encode()) == 0
        and stack.get("exc_value") == "<redacted>"
        and bool(frames)
        and all("locals" not in frame for frame in frames),
        {
            "marker_occurrences": marker_occurrences(text.encode()),
            "log_bytes": len(text),
            "exception_value": stack.get("exc_value"),
            "frame_count": len(frames),
        },
    )


async def execute() -> dict[str, Any]:
    app = build_app()
    body = json.dumps({"question": MARKER_BODY}).encode()
    async with app.router.lifespan_context(app):
        status, headers, raw, raised = await drive_request(app, body)
    sentry_sdk.flush()
    records = _CAPTURE.getvalue()

    check_init()
    headers_list, events, leaked = check_wire()
    coverage = check_coverage(events)
    check_envelope_headers(headers_list, coverage)
    check_error_event(events, coverage)
    request_id = check_public_response(status, headers, raw, raised)
    check_logs(records, request_id)

    types: dict[str, int] = {}
    for item_header, _ in events:
        name = str(item_header.get("type"))
        types[name] = types.get(name, 0) + 1
    report = {
        "observed_at": datetime.now(UTC).isoformat(),
        "scope": (
            "Real sentry_sdk init and envelope serialization for the actual app.main application, "
            "driven in process over ASGI with an in-memory transport. No Sentry ingest, provider, "
            "Redis, or remote write is used, so external ingestion, alert routing, and delivery "
            "remain unverified."
        ),
        "base_commit": base_commit(),
        "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sdk_version": sentry_sdk.VERSION,
        "transport": {
            "class": type(TRANSPORT).__name__,
            "dsn": DUMMY_DSN,
            "network_calls": "none",
        },
        "envelope_count": len(TRANSPORT.wire),
        "envelope_item_types": types,
        "pre_scrub_marker_paths": {
            "error": coverage["error_paths"],
            "transaction": coverage["transaction_paths"],
        },
        "marker_occurrences_after_transport": leaked,
        "checks": CHECKS,
        "passed": all(check["passed"] for check in CHECKS),
        "passed_count": sum(check["passed"] for check in CHECKS),
        "check_count": len(CHECKS),
    }
    return report


def base_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    with contextlib.redirect_stdout(_CAPTURE):
        report = asyncio.run(execute())
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
