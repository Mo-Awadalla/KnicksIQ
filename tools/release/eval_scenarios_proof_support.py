"""Shared plumbing for the candidate-proof scenarios.

One loopback stand-in for a bound candidate that preflights and signs exactly as
the real proof surface does, one ASGI driver for the real wrapper, and one
proven fixture: an approval, one admitted upstream attempt on a loopback fake
wire, a signed collection and a sealed ledger. Nothing here talks to a provider,
PostgreSQL, Redis or Qdrant.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app.evaluation.candidate_proof import (
    CHALLENGE_HEADER,
    PREFLIGHT_PATH,
    PROOF_HEADER,
    ProofSigner,
    RunProofKey,
    canonical_digest,
    encode_header,
    preflight_body,
)
from app.evaluation.provider_guard import RunBinding
from eval_scenario_fixtures import write_dataset
from eval_scenario_support import run_cli
from eval_scenarios_budget_support import (
    PREAMBLE,
    approval_for,
    driver,
    issue,
    proof_key_for,
    sealed,
    wire,
)
from eval_scenarios_service_support import service_collect, synthetic_identity


def signer_of(binding: RunBinding, key: RunProofKey) -> ProofSigner:
    return ProofSigner(
        key,
        run_id=binding.run_id,
        approval_sha256=binding.approval_sha256,
        config_sha256=binding.config_sha256,
        scope=binding.scope,
    )


class SigningCandidate(BaseHTTPRequestHandler):
    """A loopback stand-in for a bound candidate: it preflights and signs like the real one."""

    signer: ProofSigner
    refuse_preflight = False

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.rstrip("/") == PREFLIGHT_PATH:
            self._preflight(body)
            return
        self.server.requests.append(body)  # type: ignore[attr-defined]
        nonce = str(self.headers.get(CHALLENGE_HEADER) or "")
        payload = {
            "answer": "Synthetic.",
            "citations": [],
            "tool_calls": [{"stage": "orchestrate", "tool": "llm_orchestrate"}],
            "outcome": "clarify",
            "request_id": str(self.headers.get("X-Request-ID") or ""),
        }
        proof = self.signer.sign(
            kind="response",
            nonce=nonce,
            request_sha256=canonical_digest(body),
            http_status=200,
            response_sha256=canonical_digest(payload),
        )
        self._reply(200, payload, proof.as_dict())

    def _preflight(self, challenge: dict[str, Any]) -> None:
        signer = self.signer
        if self.refuse_preflight:
            self._reply(404, {"error": {"code": "no_preflight"}}, None)
            return
        nonce = str(challenge.get("nonce") or "")
        payload = preflight_body(
            nonce=nonce,
            run_id=signer.run_id,
            config_sha256=signer.config_sha256,
            scope=signer.scope,
            proof_scope=signer.proof_scope,
            public_key=signer.public_key,
        )
        proof = signer.sign(
            kind="preflight",
            nonce=nonce,
            request_sha256=canonical_digest(challenge),
            http_status=200,
            response_sha256=canonical_digest(payload),
        )
        self._reply(200, payload, proof.as_dict())

    def _reply(self, status: int, payload: dict[str, Any], proof: dict[str, Any] | None) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        if proof is not None:
            self.send_header(PROOF_HEADER, encode_header(proof))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args: Any) -> None:
        return


@contextmanager
def signing_candidate(
    binding: RunBinding, key: RunProofKey, *, refuse_preflight: bool = False
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    handler = type(
        "BoundSigningCandidate",
        (SigningCandidate,),
        {"signer": signer_of(binding, key), "refuse_preflight": refuse_preflight},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.requests = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server.requests  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()


def call_asgi(
    app: Any, *, path: str, body: dict[str, Any], headers: list[tuple[bytes, bytes]] | None = None
) -> tuple[int, dict[str, str], dict[str, Any]]:
    """Drive one ASGI request through the real wrapper: status, headers and parsed body."""
    import asyncio

    sent: list[dict[str, Any]] = []
    incoming = [{"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}]

    async def receive() -> dict[str, Any]:
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": list(headers or []),
        "query_string": b"",
        "http_version": "1.1",
        "scheme": "http",
        "server": ("127.0.0.1", 0),
        "client": ("127.0.0.1", 1),
    }
    asyncio.run(app(scope, receive, send))
    start = sent[0]
    response_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1") for key, value in start["headers"]
    }
    payload = b"".join(
        message["body"] for message in sent if message["type"] == "http.response.body"
    )
    return int(start["status"]), response_headers, json.loads(payload or b"{}")


def proven_run(directory: Path) -> dict[str, Any]:
    """Approve, admit one upstream attempt on a fake wire, collect signed, then seal."""
    questions, expectations = write_dataset(directory)
    identity, labels, mapping = synthetic_identity(directory, questions, expectations)
    responses = directory / "responses.jsonl"
    with wire() as (upstream, _):
        _, binding = approval_for(
            directory, base_url=upstream, cap=8, identity=identity, labels=labels
        )
        config, announced = issue(directory, binding, "run")
        spent = driver(
            directory,
            "spend",
            PREAMBLE
            + f"""
bind_run_guard()
adapter({binding.provider_base_url!r}, {binding.provider_model!r})._generate_sync("s", "u")
print(json.dumps({{"ok": True}}))
""",
            env={"EVAL_RUN_CONFIG": str(config), "EVAL_RUN_CONFIG_SHA256": announced},
        )
    key = proof_key_for(binding)
    with signing_candidate(binding, key) as (base_url, _):
        collected = service_collect(
            directory, base_url, questions, expectations, responses, config, announced
        )
    sealed(binding)
    return {
        "binding": binding,
        "key": key,
        "config": config,
        "announced": announced,
        "questions": questions,
        "expectations": expectations,
        "mapping": mapping,
        "responses": responses,
        "spent": spent,
        "collected": collected,
    }


def score_service(run: dict[str, Any], responses: Path, output: Path):
    return run_cli(
        [
            "score",
            "--questions",
            str(run["questions"]),
            "--expectations",
            str(run["expectations"]),
            "--mapping",
            str(run["mapping"]),
            "--responses",
            str(responses),
            "--profile",
            "service",
            "--run-config",
            str(run["config"]),
            "--run-config-sha256",
            run["announced"],
            "--output",
            str(output),
        ],
        cwd=output.parent,
    )


def rows_of(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_rows(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    return path
