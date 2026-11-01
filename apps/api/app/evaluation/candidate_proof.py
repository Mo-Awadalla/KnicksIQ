"""Candidate-originated proof that one service response came from the bound run.

The attempt ledger proves how many upstream attempts a run was allowed to spend.
It cannot prove that a recorded response came from the guarded candidate at all:
a row written by a collector, or a response captured under a different run, can
carry any stamp it likes. This module closes that gap with Ed25519.

The operator's parent process generates one key pair per run. The public key is
bound into the run configuration, so ``config_sha256`` and therefore the attempt
ledger's claim cover the very key that signs. The private key is handed to the
candidate process through its environment only; it is never written into an
approval, a configuration, a ledger, an artifact or a log.

The candidate signs a statement for each analyst response it produced and for a
preflight challenge it answered before the first analyst request was sent. The
statement binds the run identity, the configuration, the proof scope, the
challenge nonce, the exact canonical digest of the request, the HTTP status and
the exact canonical digest of the response body. The collector verifies it
before accepting a record; scoring re-verifies it offline from the public key in
the run configuration, so a fresh score cannot manufacture evidence.

A loopback fake keeps ``scope`` ``local_fake``: the proof is real, the quality
claim is not, and scoring blocks it as quality evidence.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import itertools
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PROOF_SCHEMA = "evaluation-response-proof-v1"
CHALLENGE_SCHEMA = "evaluation-proof-challenge-v1"
PREFLIGHT_SCHEMA = "evaluation-preflight-v1"
PREFLIGHT_PATH = "/evaluation/proof/preflight"
CHALLENGE_HEADER = "x-eval-challenge"
PROOF_HEADER = "x-eval-proof"
ENV_PROOF_KEY = "EVAL_RUN_PROOF_KEY"
PROOF_KINDS = frozenset({"response", "preflight"})
SCOPES = frozenset({"provider", "local_fake"})
PROOF_SCOPES = frozenset({"service"})
DEFAULT_PROOF_SCOPE = "service"
NONCE_BYTES = 16

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX128 = re.compile(r"^[0-9a-f]{128}$")
_NONCE = re.compile(r"^[0-9a-f]{32}$")

STATEMENT_FIELDS = (
    "schema",
    "kind",
    "run_id",
    "approval_sha256",
    "config_sha256",
    "scope",
    "proof_scope",
    "nonce",
    "request_sha256",
    "http_status",
    "response_sha256",
    "public_key",
    "issued_at",
    "sequence",
)


class ProofError(ValueError):
    """A candidate proof is absent, malformed, mismatched or unsigned."""


def canonical_digest(value: Any) -> str:
    """The one canonical form both sides hash: sorted keys, no whitespace."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def new_nonce() -> str:
    return secrets.token_hex(NONCE_BYTES)


def is_nonce(value: Any) -> bool:
    """A challenge nonce is a fresh 16-byte value; a collector may not replay one."""
    return isinstance(value, str) and bool(_NONCE.match(value))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.match(value))


def _is_hex128(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX128.match(value))


def _raw_public(seed_hex: str) -> tuple[Ed25519PrivateKey, str]:
    if not _is_hex64(seed_hex):
        raise ProofError("an Ed25519 private key is 32 bytes of lowercase hex")
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))
    return key, key.public_key().public_bytes_raw().hex()


@dataclass(frozen=True)
class RunProofKey:
    """The per-run key pair. The private half never leaves the two processes' memory."""

    public_key: str
    private_key: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        if not _is_hex64(self.public_key):
            raise ProofError("the run proof public key is 32 bytes of lowercase hex")
        if self.private_key and not _is_hex64(self.private_key):
            raise ProofError("the run proof private key is 32 bytes of lowercase hex")


def generate_keypair() -> RunProofKey:
    """One fresh Ed25519 pair for exactly one run, generated in the parent's memory."""
    seed = Ed25519PrivateKey.generate().private_bytes_raw().hex()
    _, public_key = _raw_public(seed)
    return RunProofKey(public_key=public_key, private_key=seed)


def public_key_for(seed_hex: str) -> str:
    """Derive the public half a candidate must match against its bound configuration."""
    return _raw_public(seed_hex)[1]


def sign_statement(private_key: str, statement: Mapping[str, Any]) -> str:
    key, _ = _raw_public(private_key)
    payload = json.dumps(dict(statement), sort_keys=True, separators=(",", ":"))
    return key.sign(payload.encode()).hex()


def verify_statement(public_key: str, statement: Mapping[str, Any], signature: str) -> None:
    """Raise unless ``signature`` is this statement's Ed25519 signature by ``public_key``."""
    if not _is_hex64(public_key):
        raise ProofError("the verifying public key is not a raw Ed25519 key")
    if not _is_hex128(signature):
        raise ProofError("the candidate proof carries no usable signature")
    payload = json.dumps(dict(statement), sort_keys=True, separators=(",", ":"))
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(
            bytes.fromhex(signature), payload.encode()
        )
    except (InvalidSignature, ValueError) as exc:
        raise ProofError("the candidate proof signature does not verify") from exc


def encode_header(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_header(value: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        raise ProofError("the proof header is empty")
    text = value.strip()
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        payload = json.loads(raw)
    except (binascii.Error, ValueError, json.JSONDecodeError) as exc:
        raise ProofError("the proof header is not a base64url JSON object") from exc
    if not isinstance(payload, dict):
        raise ProofError("the proof header is not an object")
    return payload


@dataclass(frozen=True)
class ResponseProof:
    """One signed statement: what run answered, which request, which response."""

    kind: str
    run_id: str
    approval_sha256: str
    config_sha256: str
    scope: str
    proof_scope: str
    nonce: str
    request_sha256: str
    http_status: int
    response_sha256: str
    public_key: str
    issued_at: str
    sequence: int
    signature: str

    def statement(self) -> dict[str, Any]:
        return {
            "schema": PROOF_SCHEMA,
            "kind": self.kind,
            "run_id": self.run_id,
            "approval_sha256": self.approval_sha256,
            "config_sha256": self.config_sha256,
            "scope": self.scope,
            "proof_scope": self.proof_scope,
            "nonce": self.nonce,
            "request_sha256": self.request_sha256,
            "http_status": self.http_status,
            "response_sha256": self.response_sha256,
            "public_key": self.public_key,
            "issued_at": self.issued_at,
            "sequence": self.sequence,
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.statement(), "signature": self.signature}

    def verify(self, public_key: str) -> None:
        """Check this statement against the key bound in the run configuration."""
        if self.public_key != public_key:
            raise ProofError(
                "the proof names a public key that is not the one bound in the run configuration"
            )
        verify_statement(public_key, self.statement(), self.signature)

    @classmethod
    def from_dict(cls, raw: Any) -> ResponseProof:
        if not isinstance(raw, Mapping):
            raise ProofError("the record proof is not an object")
        missing = [name for name in (*STATEMENT_FIELDS, "signature") if name not in raw]
        if missing:
            raise ProofError("the record proof is incomplete: " + ", ".join(missing))
        for name in (
            "run_id",
            "scope",
            "proof_scope",
            "nonce",
            "issued_at",
        ):
            if not isinstance(raw[name], str) or not raw[name].strip():
                raise ProofError(f"the record proof carries no {name}")
        for name in (
            "approval_sha256",
            "config_sha256",
            "request_sha256",
            "response_sha256",
            "public_key",
        ):
            if not _is_hex64(raw[name]):
                raise ProofError(f"the record proof {name} is not a sha256 digest")
        if raw["schema"] != PROOF_SCHEMA:
            raise ProofError("the record proof has an unknown schema")
        if raw["kind"] not in PROOF_KINDS:
            raise ProofError(f"the record proof kind {raw['kind']!r} is unknown")
        if raw["scope"] not in SCOPES:
            raise ProofError(f"the record proof scope {raw['scope']!r} is unknown")
        if raw["proof_scope"] not in PROOF_SCOPES:
            raise ProofError(f"the record proof scope {raw['proof_scope']!r} is unknown")
        if not _NONCE.match(raw["nonce"]):
            raise ProofError("the record proof nonce is not a challenge nonce")
        if not _is_hex128(raw["signature"]):
            raise ProofError("the record proof carries no usable signature")
        status = raw["http_status"]
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            raise ProofError("the record proof binds no real HTTP status")
        sequence = raw["sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ProofError("the record proof binds no signing sequence")
        return cls(
            kind=str(raw["kind"]),
            run_id=str(raw["run_id"]),
            approval_sha256=str(raw["approval_sha256"]),
            config_sha256=str(raw["config_sha256"]),
            scope=str(raw["scope"]),
            proof_scope=str(raw["proof_scope"]),
            nonce=str(raw["nonce"]),
            request_sha256=str(raw["request_sha256"]),
            http_status=status,
            response_sha256=str(raw["response_sha256"]),
            public_key=str(raw["public_key"]),
            issued_at=str(raw["issued_at"]),
            sequence=sequence,
            signature=str(raw["signature"]),
        )

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ResponseProof | None:
        """The proof a record carries, or ``None``. A malformed proof is never skipped."""
        raw = record.get("proof")
        if raw is None:
            return None
        return cls.from_dict(raw)

    @classmethod
    def from_header(cls, value: str) -> ResponseProof:
        return cls.from_dict(decode_header(value))


class ProofSigner:
    """The candidate-side signer for one bound run. Holds the private key in memory only."""

    def __init__(
        self,
        key: RunProofKey,
        *,
        run_id: str,
        approval_sha256: str,
        config_sha256: str,
        scope: str,
        proof_scope: str = DEFAULT_PROOF_SCOPE,
    ) -> None:
        if not key.private_key:
            raise ProofError("the candidate has no run private key to sign with")
        if public_key_for(key.private_key) != key.public_key:
            raise ProofError("the candidate proof private key does not match its public key")
        if scope not in SCOPES:
            raise ProofError(f"the run scope {scope!r} is unknown")
        if proof_scope not in PROOF_SCOPES:
            raise ProofError(f"the proof scope {proof_scope!r} is unknown")
        self._private_key = key.private_key
        self.public_key = key.public_key
        self.run_id = run_id
        self.approval_sha256 = approval_sha256
        self.config_sha256 = config_sha256
        self.scope = scope
        self.proof_scope = proof_scope
        self._sequence = itertools.count(1)

    def __repr__(self) -> str:
        return f"ProofSigner(run_id={self.run_id!r}, public_key={self.public_key!r})"

    def sign(
        self, *, kind: str, nonce: str, request_sha256: str, http_status: int, response_sha256: str
    ) -> ResponseProof:
        if kind not in PROOF_KINDS:
            raise ProofError(f"proof kind {kind!r} is unknown")
        if not _NONCE.match(nonce):
            raise ProofError("refusing to sign without a challenge nonce")
        statement = {
            "schema": PROOF_SCHEMA,
            "kind": kind,
            "run_id": self.run_id,
            "approval_sha256": self.approval_sha256,
            "config_sha256": self.config_sha256,
            "scope": self.scope,
            "proof_scope": self.proof_scope,
            "nonce": nonce,
            "request_sha256": request_sha256,
            "http_status": http_status,
            "response_sha256": response_sha256,
            "public_key": self.public_key,
            "issued_at": _now(),
            "sequence": next(self._sequence),
        }
        return ResponseProof.from_dict(
            {**statement, "signature": sign_statement(self._private_key, statement)}
        )


def challenge_payload(
    *,
    nonce: str,
    run_id: str,
    config_sha256: str,
    scope: str,
    proof_scope: str = DEFAULT_PROOF_SCOPE,
) -> dict[str, Any]:
    return {
        "schema": CHALLENGE_SCHEMA,
        "nonce": nonce,
        "run_id": run_id,
        "config_sha256": config_sha256,
        "scope": scope,
        "proof_scope": proof_scope,
    }


def preflight_body(
    *,
    nonce: str,
    run_id: str,
    config_sha256: str,
    scope: str,
    proof_scope: str,
    public_key: str,
) -> dict[str, Any]:
    """The preflight answer the candidate returns before any analyst request is sent."""
    return {
        "schema": PREFLIGHT_SCHEMA,
        "ready": True,
        "nonce": nonce,
        "run_id": run_id,
        "config_sha256": config_sha256,
        "scope": scope,
        "proof_scope": proof_scope,
        "public_key": public_key,
    }


__all__ = [
    "CHALLENGE_HEADER",
    "CHALLENGE_SCHEMA",
    "DEFAULT_PROOF_SCOPE",
    "ENV_PROOF_KEY",
    "PREFLIGHT_PATH",
    "PREFLIGHT_SCHEMA",
    "PROOF_HEADER",
    "PROOF_KINDS",
    "PROOF_SCHEMA",
    "PROOF_SCOPES",
    "ProofError",
    "ProofSigner",
    "ResponseProof",
    "RunProofKey",
    "STATEMENT_FIELDS",
    "canonical_digest",
    "challenge_payload",
    "decode_header",
    "encode_header",
    "generate_keypair",
    "is_nonce",
    "new_nonce",
    "preflight_body",
    "public_key_for",
    "sign_statement",
    "verify_statement",
]
