"""The HTTP exchange one collection makes with the candidate, and its failures.

The transport is deliberately narrow: it proves a candidate endpoint is loopback,
builds the one request model the API accepts from a labelled case, sends it, and
records exactly what was sent and received. It never consults ambient proxy
settings, never follows a redirect and never decides whether a run is
provider-free, bound or attested; that policy lives in
:mod:`app.evaluation.runner`.

:class:`RunnerError` is the one collection failure type both layers raise, so a
transport refusal and a run-level refusal reach the caller as the same error.
"""

from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from app.evaluation.candidate_proof import (
    CHALLENGE_HEADER,
    PROOF_HEADER,
    ProofError,
    ResponseProof,
    canonical_digest,
)
from app.evaluation.chat_stream import frame, response_from_events
from app.evaluation.labels import ExpectationCase
from app.evaluation.provider_guard import is_loopback_host


class RunnerError(RuntimeError):
    """Collection could not honour the requested profile."""


class _LocalOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect could move a loopback request off the candidate; it is refused."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str):
        raise RunnerError(f"candidate API answered {code} redirect to {newurl}; refused")


def direct_opener() -> urllib.request.OpenerDirector:
    """An opener that never consults ambient proxy settings and never follows redirects."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _LocalOnlyRedirects())


def validate_base_url(base_url: str) -> str:
    """Only a loopback candidate is accepted, so a disabled run stays a local measurement."""
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"}:
        raise RunnerError(f"{base_url} is not an HTTP endpoint")
    host = parts.hostname
    if not is_loopback_host(host):
        raise RunnerError(
            f"{host or base_url} is not a loopback candidate; collection never leaves the "
            "machine (any loopback address, ::1 or localhost)"
        )
    return base_url


def build_request(case: ExpectationCase, *, season: str) -> dict[str, Any]:
    """Exactly the fields the public request model accepts, and nothing imagined."""
    return {
        "kind": "message",
        "message": case.question,
        "request_id": str(uuid.uuid4()),
        "expected_revision": 0,
    }


def collect_case(
    base_url: str,
    case: ExpectationCase,
    *,
    season: str,
    timeout: float,
    challenge: str = "",
) -> dict[str, Any]:
    validate_base_url(base_url)
    token, revision, history = secrets.token_urlsafe(32), 0, []
    started, started_at = time.perf_counter(), datetime.now(UTC).isoformat()
    commands = [entry["content"] for entry in case.context if entry["role"] == "user"]
    commands.append(case.question)
    requests: list[dict[str, Any]] = [
        {
            "kind": "message",
            "request_id": str(uuid.uuid4()),
            "expected_revision": 0,
            "message": message,
        }
        for message in commands
    ]
    request_body = requests[0]
    status, body, proof = 0, {}, None
    for request_body in requests:
        request_body["expected_revision"] = revision
        headers = {
            "Content-Type": "application/json",
            "X-Chat-Token": token,
            "X-Request-ID": request_body["request_id"],
        }
        if challenge:
            headers[CHALLENGE_HEADER] = challenge
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/turns",
            data=json.dumps(request_body).encode(),
            headers=headers,
            method="POST",
        )
        events = []
        try:
            with direct_opener().open(request, timeout=timeout) as response:
                status, lines = int(response.status), []
                for raw in response:
                    line = raw.decode("utf-8").rstrip("\r\n")
                    if line:
                        lines.append(line)
                    else:
                        event, lines = frame("\n".join(lines)), []
                        if event:
                            if event[0] == "evaluation_proof":
                                proof = event[1]
                            else:
                                events.append(event)
                if lines:
                    raise ValueError("unterminated chat frame")
                body = response_from_events(events)
                revision = body.get("revision", revision)
        except urllib.error.HTTPError as exc:
            status, body = int(exc.code), json.loads(exc.read() or b"{}")
            proof_header = (exc.headers or {}).get(PROOF_HEADER)
            if proof_header:
                try:
                    proof = ResponseProof.from_header(proof_header).as_dict()
                except ProofError:
                    proof = None
            break
        except RunnerError:
            raise
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, StopIteration) as exc:
            body = {"error": {"code": "transport_failure", "message": type(exc).__name__}}
            break
        history.append({"request": request_body, "response": body})
        if body.get("status") != "complete":
            break
    record = {
        "case_id": case.id,
        "request_id": request_body["request_id"],
        "expected_revision": request_body["expected_revision"],
        "request": request_body,
        "context_turns": history[:-1],
        "declared_context": list(case.context),
        "response": body,
        "http_status": status,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "started_at": started_at,
        "response_sha256": canonical_digest(body),
    }
    if challenge:
        record["challenge"] = challenge
        if proof:
            record["proof"] = proof
    return record


__all__ = [
    "RunnerError",
    "build_request",
    "collect_case",
    "direct_opener",
    "validate_base_url",
]
