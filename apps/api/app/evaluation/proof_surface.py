"""The evaluation-only proof surface a bound service candidate serves.

This is the wrapper the service entrypoint applies to the application: one signed
statement per analyst response, and one signed statement for a preflight
challenge that touches no provider. It enforces its own precondition — a
model-bearing request without a challenge nonce is refused before the
application runs, so the guarded adapter never sends a paid request whose
response could not be proven.

Nothing here imports the application or binds a run, so the protocol can be
exercised without a bound process.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.evaluation.candidate_proof import (
    CHALLENGE_HEADER,
    CHALLENGE_SCHEMA,
    ENV_PROOF_KEY,
    PREFLIGHT_PATH,
    PROOF_HEADER,
    PROOF_SCOPES,
    ProofError,
    ProofSigner,
    RunProofKey,
    canonical_digest,
    encode_header,
    is_nonce,
    preflight_body,
    public_key_for,
)
from app.evaluation.provider_guard import RunBinding

CHALLENGE_PATHS = frozenset({"/analysis/query"})
MAX_BODY_BYTES = 8 << 20

Message = dict[str, Any]
Scope = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


def signer_for(binding: RunBinding, environ: Mapping[str, str]) -> ProofSigner:
    """Build the run's signer, or fail before readiness if its key cannot sign for it."""
    seed = str(environ.get(ENV_PROOF_KEY) or "").strip()
    if not seed:
        raise ProofError(
            f"{ENV_PROOF_KEY} is unset; a service candidate cannot prove its own responses"
        )
    if public_key_for(seed) != binding.proof_public_key:
        raise ProofError(
            f"{ENV_PROOF_KEY} does not match the public key bound in run {binding.run_id}"
        )
    return ProofSigner(
        RunProofKey(public_key=binding.proof_public_key, private_key=seed),
        run_id=binding.run_id,
        approval_sha256=binding.approval_sha256,
        config_sha256=binding.config_sha256,
        scope=binding.scope,
    )


def _header(scope: Mapping[str, Any], name: str) -> str:
    wanted = name.lower().encode()
    for key, value in scope.get("headers") or []:
        if key.lower() == wanted:
            return value.decode("latin-1")
    return ""


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise ProofError("the client disconnected before its body was complete")
        chunk = message.get("body") or b""
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise ProofError("the request body is larger than this surface signs")
        chunks.append(chunk)
        if not message.get("more_body"):
            return b"".join(chunks)


def _json_object(raw: bytes, what: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise ProofError(f"the {what} is not JSON") from exc
    if not isinstance(payload, dict):
        raise ProofError(f"the {what} is not an object")
    return payload


async def _send_json(
    send: Send, status: int, payload: Mapping[str, Any], *, proof: str | None = None
) -> None:
    body = json.dumps(dict(payload), sort_keys=True).encode()
    extra = [] if proof is None else [(PROOF_HEADER.encode(), proof.encode())]
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *extra,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class CandidateProofMiddleware:
    """Signs one statement per challenged response; never signs a body it cannot read."""

    def __init__(self, app: Any, signer: ProofSigner) -> None:
        self.app = app
        self.signer = signer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "").rstrip("/") or "/"
        if path == PREFLIGHT_PATH:
            await self._preflight(scope, receive, send)
            return
        challenge = _header(scope, CHALLENGE_HEADER).strip()
        if not challenge:
            if scope.get("method") == "POST" and path in CHALLENGE_PATHS:
                await _send_json(
                    send,
                    400,
                    {
                        "error": {
                            "code": "evaluation_challenge_required",
                            "message": (
                                "this candidate is bound to a bounded evaluation run; a "
                                "model-bearing request needs a challenge nonce"
                            ),
                        }
                    },
                )
                return
            await self.app(scope, receive, send)
            return
        try:
            body = await _read_body(receive)
            request_payload = _json_object(body, "request")
            if not is_nonce(challenge):
                raise ProofError("the challenge header is not a challenge nonce")
        except ProofError as exc:
            await _send_json(
                send, 400, {"error": {"code": "evaluation_challenge_invalid", "message": str(exc)}}
            )
            return
        await self._signed(scope, body, request_payload, challenge, send)

    async def _preflight(self, scope: Scope, receive: Receive, send: Send) -> None:
        """A signed challenge round trip: no provider, no ledger admission, no side effect."""
        if scope.get("method") != "POST":
            await _send_json(send, 405, {"error": {"code": "preflight_needs_post"}})
            return
        try:
            challenge = _json_object(await _read_body(receive), "preflight challenge")
            self._check_challenge(challenge)
            nonce = challenge["nonce"]
        except ProofError as exc:
            await _send_json(
                send, 409, {"error": {"code": "preflight_refused", "message": str(exc)}}
            )
            return
        payload = preflight_body(
            nonce=nonce,
            run_id=self.signer.run_id,
            config_sha256=self.signer.config_sha256,
            scope=self.signer.scope,
            proof_scope=self.signer.proof_scope,
            public_key=self.signer.public_key,
        )
        proof = self.signer.sign(
            kind="preflight",
            nonce=nonce,
            request_sha256=canonical_digest(challenge),
            http_status=200,
            response_sha256=canonical_digest(payload),
        )
        await _send_json(send, 200, payload, proof=encode_header(proof.as_dict()))

    def _check_challenge(self, challenge: Mapping[str, Any]) -> None:
        if challenge.get("schema") != CHALLENGE_SCHEMA:
            raise ProofError("the preflight challenge schema is unknown")
        if not is_nonce(challenge.get("nonce")):
            raise ProofError("the preflight challenge carries no fresh nonce")
        for name, value in (
            ("run_id", self.signer.run_id),
            ("config_sha256", self.signer.config_sha256),
            ("scope", self.signer.scope),
        ):
            if challenge.get(name) != value:
                raise ProofError(f"the preflight challenge binds a different {name}")
        proof_scope = challenge.get("proof_scope")
        if proof_scope is not None and proof_scope not in PROOF_SCOPES:
            raise ProofError("the preflight challenge declares an unknown proof scope")

    async def _signed(
        self,
        scope: Scope,
        body: bytes,
        request_payload: dict[str, Any],
        nonce: str,
        send: Send,
    ) -> None:
        """Buffer the application's answer, sign its exact digests, then release it."""
        request_sha256 = canonical_digest(request_payload)
        status = 0
        headers: list[tuple[bytes, bytes]] = []
        parts: list[bytes] = []
        size = 0
        complete = False

        async def capture(message: Message) -> None:
            nonlocal status, headers, size, complete
            if message["type"] == "http.response.start":
                status = int(message.get("status") or 0)
                headers = list(message.get("headers") or [])
                return
            if message["type"] != "http.response.body":
                return
            chunk = message.get("body") or b""
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                raise ProofError("the response body is larger than this surface signs")
            parts.append(chunk)
            complete = not message.get("more_body")

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        try:
            await self.app(scope, replay, capture)
            if not status or not complete:
                raise ProofError("the application produced no complete response to sign")
            response_payload = _json_object(b"".join(parts), "response")
        except ProofError as exc:
            await _send_json(
                send, 502, {"error": {"code": "evaluation_proof_failed", "message": str(exc)}}
            )
            return
        proof = self.signer.sign(
            kind="response",
            nonce=nonce,
            request_sha256=request_sha256,
            http_status=status,
            response_sha256=canonical_digest(response_payload),
        )
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    *headers,
                    (PROOF_HEADER.encode(), encode_header(proof.as_dict()).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"".join(parts)})
