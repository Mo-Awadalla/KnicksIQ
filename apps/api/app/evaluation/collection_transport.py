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
        "question": case.question,
        "season": season,
        "context": list(case.context),
        "turn_id": uuid.uuid4().hex,
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
    """Send one case as one turn, recording the exact request and the exact response."""
    request_body = build_request(case, season=season)
    payload = json.dumps(request_body).encode()
    sent_request_id = uuid.uuid4().hex
    headers = {"Content-Type": "application/json", "X-Request-ID": sent_request_id}
    if challenge:
        headers[CHALLENGE_HEADER] = challenge
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/analysis/query",
        data=payload,
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    started_at = datetime.now(UTC).isoformat()
    status = 0
    body: dict[str, Any] = {}
    proof_header = ""
    try:
        with direct_opener().open(request, timeout=timeout) as response:
            status = int(response.status)
            raw = response.read()
            proof_header = response.headers.get(PROOF_HEADER) or ""
            body = json.loads(raw or b"{}")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        raw = exc.read()
        proof_header = (exc.headers or {}).get(PROOF_HEADER) or ""
        try:
            parsed = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            parsed = {"error": {"raw": raw.decode("utf-8", "replace")[:500]}}
        body = parsed if isinstance(parsed, dict) else {"error": {"non_object_response": True}}
    except RunnerError:
        raise
    except (urllib.error.URLError, TimeoutError) as exc:
        body = {"error": {"code": "transport_failure", "message": type(exc).__name__}}
    latency_ms = (time.perf_counter() - started) * 1000
    if not isinstance(body, dict):
        body = {"error": {"code": "non_object_response"}}
    record: dict[str, Any] = {
        "case_id": case.id,
        "request_id": sent_request_id,
        "turn_id": request_body["turn_id"],
        "session_token": body.get("session_token"),
        "expected_revision": request_body["expected_revision"],
        "request": request_body,
        "response": body,
        "http_status": status,
        "latency_ms": round(latency_ms, 1),
        "started_at": started_at,
        "response_sha256": canonical_digest(body),
    }
    if challenge:
        record["challenge"] = challenge
        if proof_header:
            try:
                record["proof"] = ResponseProof.from_header(proof_header).as_dict()
            except ProofError as exc:
                record["proof_problem"] = str(exc)
    return record


def count_provider_stages(record: dict[str, Any]) -> int:
    response = record.get("response") or {}
    return sum(
        1
        for entry in response.get("tool_calls") or []
        if isinstance(entry, dict)
        and (
            entry.get("stage") in {"orchestrate", "revise", "review"}
            or str(entry.get("tool", "")).startswith("llm_")
        )
    )


__all__ = [
    "RunnerError",
    "build_request",
    "collect_case",
    "count_provider_stages",
    "direct_opener",
    "validate_base_url",
]
