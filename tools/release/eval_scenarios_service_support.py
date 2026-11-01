"""Service-profile fixtures: the loopback candidate, the identity helper and the CLI caller.

These are the pieces every service scenario shares, not scenarios themselves. The
candidate stand-in signs like the real bound entrypoint, so a service collection
can be driven end to end without a provider, Redis, Qdrant or PostgreSQL.
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app.evaluation.candidate_proof import (  # noqa: E402
    CHALLENGE_HEADER,
    PREFLIGHT_PATH,
    PROOF_HEADER,
    ProofSigner,
    canonical_digest,
    encode_header,
    preflight_body,
)
from app.evaluation.labels import (  # noqa: E402
    evaluation_identity,
    identity_digest,
    load_labels,
)
from app.evaluation.mapping import load_mapping  # noqa: E402
from app.evaluation.provider_guard import RunBinding  # noqa: E402
from eval_scenario_fixtures import dump, synthetic_mapping
from eval_scenario_support import run_cli
from eval_scenarios_budget_support import proof_key_for


class StageCandidate(BaseHTTPRequestHandler):
    """A loopback candidate stand-in that reports one model stage per case.

    Bound to a run, it also answers the preflight challenge and signs every
    response, so a service collection can be exercised without a provider.
    """

    signer: Any = None

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.rstrip("/") == PREFLIGHT_PATH:
            self._preflight(body)
            return
        self.server.requests.append(body)  # type: ignore[attr-defined]
        payload = {
            "answer": "Synthetic.",
            "citations": [],
            "tool_calls": [{"stage": "orchestrate", "tool": "llm_orchestrate"}],
            "outcome": "clarify",
            "request_id": str(self.headers.get("X-Request-ID") or ""),
        }
        proof = None
        if self.signer is not None:
            proof = self.signer.sign(
                kind="response",
                nonce=str(self.headers.get(CHALLENGE_HEADER) or ""),
                request_sha256=canonical_digest(body),
                http_status=200,
                response_sha256=canonical_digest(payload),
            )
        self._reply(200, payload, proof)

    def _preflight(self, challenge: dict[str, Any]) -> None:
        signer = self.signer
        if signer is None:
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
        self._reply(200, payload, proof)

    def _reply(self, status: int, payload: dict[str, Any], proof: Any) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        if proof is not None:
            self.send_header(PROOF_HEADER, encode_header(proof.as_dict()))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args: Any) -> None:
        return


@contextmanager
def candidate(
    binding: RunBinding | None = None,
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Serve a stand-in candidate; bound to a run, it signs like the real entrypoint."""
    signer = None
    if binding is not None:
        signer = ProofSigner(
            proof_key_for(binding),
            run_id=binding.run_id,
            approval_sha256=binding.approval_sha256,
            config_sha256=binding.config_sha256,
            scope=binding.scope,
        )
    handler = type("StageCandidateForRun", (StageCandidate,), {"signer": signer})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.requests = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server.requests  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()


def synthetic_identity(
    directory: Path, questions: Path, expectations: Path
) -> tuple[str, str, Path]:
    """The identity an approval for this synthetic dataset must bind, and its mapping file."""
    mapping_path = dump(directory / "runtime-mapping.json", synthetic_mapping())
    labels = load_labels(questions, expectations)
    mapping = load_mapping(mapping_path)
    identity = identity_digest(
        evaluation_identity(labels, mapping_sha256=mapping.file_sha256, documents_sha256=None)
    )
    return identity, labels.labels_sha256, mapping_path


def service_collect(
    directory: Path,
    base_url: str,
    questions: Path,
    expectations: Path,
    responses: Path,
    config: Path,
    announced: str,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return run_cli(
        [
            "collect",
            "--questions",
            str(questions),
            "--expectations",
            str(expectations),
            "--base-url",
            base_url,
            "--profile",
            "service",
            "--responses",
            str(responses),
            "--run-config",
            str(config),
            "--run-config-sha256",
            announced,
            *extra,
        ],
        cwd=directory,
    )


__all__ = [
    "StageCandidate",
    "candidate",
    "service_collect",
    "synthetic_identity",
]
