"""Identical-payload timing probe on OpenCode Go.

Replays exact provider payloads captured from a live analyst run (``payloads.json``) and records
the UTC hour, transport, session-id mode, input bytes and completion tokens for every call.
Answers three questions the aggregate benchmark cannot:

1. Does latency depend on the UTC hour inside the off-peak window?
2. Does a reused TCP/TLS connection or a stable ``x-opencode-session`` id cut latency?
3. Does input size change time-to-response when the requested output is fixed?

    . /tmp/go.env
    uv run --package knicksiq-api python .../w4-latency/probe.py \
      --payloads .../before/payloads.json --out .../probe.jsonl --rounds 3 --gap-seconds 1200

Instrumentation only; it never edits or imports application state beyond the wire builders.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import certifi

TOOLS = Path(__file__).resolve().parents[4] / "tools" / "release"
import sys

sys.path.insert(0, str(TOOLS))
from app.services.llm_wire import PROTOCOLS, Request  # noqa: E402

BASE = os.environ["AI_BASE_URL"].rstrip("/")
KEY = os.environ["AI_API_KEY"]
UA = os.environ.get("AI_USER_AGENT", "knicksiq/1.0")
JSON_OBJECT = os.environ.get("ANALYST_PROVIDER_FORMAT", "json_object") != "json_schema"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def body_for(
    payload: dict[str, Any], model: str, max_tokens: int, protocol: str | None = None
) -> tuple[str, bytes, str]:
    protocol = protocol or payload.get("protocol") or "chat"
    build, _ = PROTOCOLS[protocol]
    path, value = build(
        Request(
            model=model,
            system=payload["system"],
            user=payload["user"],
            max_tokens=max_tokens,
            reasoning_effort=payload.get("reasoning_effort"),
            response_schema=None,
            json_object=JSON_OBJECT,
            openrouter=False,
            provider={},
        )
    )
    return path, json.dumps(value).encode("utf-8"), protocol


def headers(session: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
        "User-Agent": UA,
        "x-opencode-session": session,
    }


class KeepAlive:
    """One persistent HTTPS connection, the transport candidate for report_llm."""

    def __init__(self) -> None:
        parsed = urllib.parse.urlsplit(BASE)
        self.host = parsed.hostname or ""
        self.port = parsed.port or 443
        self.prefix = parsed.path.rstrip("/")
        self.conn: http.client.HTTPSConnection | None = None

    def _connect(self, timeout: float) -> http.client.HTTPSConnection:
        return http.client.HTTPSConnection(
            self.host, self.port, timeout=timeout, context=SSL_CONTEXT
        )

    def post(
        self, path: str, payload: bytes, head: dict[str, str], timeout: float
    ) -> tuple[int, bytes, float]:
        if self.conn is None:
            self.conn = self._connect(timeout)
        self.conn.timeout = timeout
        if self.conn.sock is not None:
            self.conn.sock.settimeout(timeout)
        try:
            self.conn.request("POST", self.prefix + path, body=payload, headers=head)
        except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError):
            # An idle keep-alive connection was closed by the host before this request.
            self.conn.close()
            self.conn = self._connect(timeout)
            self.conn.request("POST", self.prefix + path, body=payload, headers=head)
        response = self.conn.getresponse()
        first_byte_at = time.monotonic()
        raw = response.read()
        if response.will_close:
            self.conn.close()
            self.conn = None
        return response.status, raw, first_byte_at


def send_new(
    path: str, payload: bytes, head: dict[str, str], timeout: float
) -> tuple[int, bytes, float]:
    request = urllib.request.Request(f"{BASE}{path}", data=payload, headers=head, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
            return response.status, response.read(), time.monotonic()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), time.monotonic()


def usage(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except ValueError:
        return {}
    if not isinstance(value, dict):
        return {}
    body = value.get("usage") or {}
    reasoning = (body.get("completion_tokens_details") or {}).get("reasoning_tokens")
    if reasoning is None:
        reasoning = (body.get("output_tokens_details") or {}).get("reasoning_tokens")
    return {
        "prompt_tokens": body.get("prompt_tokens", body.get("input_tokens")),
        "completion_tokens": body.get("completion_tokens", body.get("output_tokens")),
        "reasoning_tokens": reasoning,
        "served_model": value.get("model"),
        "provider_error": (value.get("error") or None),
    }


def one(
    *,
    keepalive: KeepAlive | None,
    path: str,
    payload: bytes,
    model: str,
    protocol: str,
    session: str,
    timeout: float = 60.0,
) -> dict[str, Any]:
    started = time.monotonic()
    ttfb: float | None = None
    status = 0
    raw = b""
    error = None
    try:
        if keepalive is not None:
            status, raw, header_at = keepalive.post(path, payload, headers(session), timeout)
        else:
            status, raw, header_at = send_new(path, payload, headers(session), timeout)
        ttfb = round((header_at - started) * 1000, 1)
    except (OSError, http.client.HTTPException) as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
    latency = round((time.monotonic() - started) * 1000, 1)
    info = usage(raw)
    return {
        "at_utc": utc_now(),
        "hour_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:00Z"),
        "model": model,
        "protocol": protocol,
        "session": "stable" if session == STABLE_SESSION else "new",
        "transport": "keepalive" if keepalive is not None else "new-connection",
        "request_bytes": len(payload),
        "latency_ms": latency,
        "ttfb_ms": ttfb,
        "status": status,
        "response_bytes": len(raw),
        "finish_reason": None,
        "error": error,
        **info,
    }


STABLE_SESSION = uuid.uuid4().hex


def session_for(mode: str) -> str:
    return STABLE_SESSION if mode == "stable" else uuid.uuid4().hex


def add_note(user: str, target_bytes: int) -> str:
    value = json.loads(user)
    filler = (
        "Reference note: archived box scores are frozen at the active release and the "
        "analysis only repeats numbers present in the supplied claims. "
    )
    base = len(json.dumps(value, separators=(",", ":")))
    value["reference_notes"] = ""
    buf = [filler] * max(1, (target_bytes - base) // len(filler) + 1)
    value["reference_notes"] = "".join(buf)
    return json.dumps(value, separators=(",", ":"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payloads", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--gap-seconds", type=float, default=1200)
    args = parser.parse_args()
    payloads = json.loads(args.payloads.read_text())
    writer = payloads.get("ProposedAnswer") or payloads.get("Action")
    reviewer = payloads.get("AnswerReview")
    if not writer or not reviewer:
        raise SystemExit(f"payloads missing Action/AnswerReview: {sorted(payloads)}")
    target = {"writer": writer, "reviewer": reviewer}
    args.out.write_text("")
    keepalive = KeepAlive()
    for round_index in range(args.rounds):
        for name, payload in target.items():
            model = payload["model"]
            path, body, protocol = body_for(payload, model, payload.get("max_tokens") or 1200)
            # Four combinations: production today, session reuse, connection reuse, both.
            for transport, session_mode in (
                ("new", "new"),
                ("new", "stable"),
                ("keep", "new"),
                ("keep", "stable"),
            ):
                row = one(
                    keepalive=keepalive if transport == "keep" else None,
                    path=path,
                    payload=body,
                    model=model,
                    protocol=protocol,
                    session=session_for(session_mode),
                )
                row.update(round=round_index, payload=name, combo=f"{transport}+{session_mode}")
                with args.out.open("a") as handle:
                    handle.write(json.dumps(row) + "\n")
                print(json.dumps(row), flush=True)
        if round_index == 0 and reviewer:
            # Input-size sweep on the reviewer: fixed request, only padding changes.
            path, _, protocol = body_for(reviewer, reviewer["model"], reviewer.get("max_tokens") or 1200)
            for size in (14000, 16000, 20000, 24000, 32000):
                user = add_note(reviewer["user"], size)
                payload = dict(reviewer)
                payload["user"] = user
                path, body, protocol = body_for(
                    payload, reviewer["model"], payload.get("max_tokens") or 1200
                )
                row = one(
                    keepalive=keepalive,
                    path=path,
                    payload=body,
                    model=reviewer["model"],
                    protocol=protocol,
                    session=session_for("stable"),
                )
                row.update(round=0, payload=f"reviewer-size-{size}", combo="keep+stable")
                with args.out.open("a") as handle:
                    handle.write(json.dumps(row) + "\n")
                print(json.dumps(row), flush=True)
            # Owner-facing model options on the same reviewer payload (not a switch).
            for model in ("deepseek-v4.1-flash", "deepseek-v4-flash"):
                path, body, protocol = body_for(reviewer, model, 1200, protocol="chat")
                for _ in range(2):
                    row = one(
                        keepalive=keepalive,
                        path=path,
                        payload=body,
                        model=model,
                        protocol="chat",
                        session=session_for("stable"),
                    )
                    row.update(round=0, payload="reviewer-model-option", combo="keep+stable")
                    with args.out.open("a") as handle:
                        handle.write(json.dumps(row) + "\n")
                    print(json.dumps(row), flush=True)
        if round_index + 1 < args.rounds:
            time.sleep(args.gap_seconds)


if __name__ == "__main__":
    main()
