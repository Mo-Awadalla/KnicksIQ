"""The approval-bound guard every real provider request passes before the wire.

The run configuration is derived from the approval and written by the parent
before the candidate starts. It binds the per-run Ed25519 public key the
candidate signs its responses with, so the configuration digest, and therefore
the durable claim in the attempt ledger, cover the one key that can speak for
this run. A service candidate binds the configuration at startup, before it
answers readiness, which leaves that claim. The adapter then calls
:func:`require_run_guard` at its single HTTP boundary, so a bare constructor is
guarded too. Ordinary production never binds a guard and keeps its current
provider policy.

The approval artifact itself, and the failures it shares with the guard, live in
:mod:`app.evaluation.provider_approval`. This module owns the issued run
configuration, the classification of the bound upstream and admission.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.evaluation.attempt_ledger import AttemptLedger
from app.evaluation.candidate_proof import RunProofKey, generate_keypair
from app.evaluation.ledger_state import LedgerBinding
from app.evaluation.provider_approval import (
    ApprovalError,
    GuardError,
    ServiceApproval,
    digest,
    is_hex64,
)
from app.evaluation.spend_bound import (
    MAX_ATTEMPTS,
    PROVIDER_BASE_URL,
    PROVIDER_MODEL,
    SpendBound,
    SpendError,
)

CONFIG_SCHEMA = "evaluation-run-config-v3"
ENV_CONFIG = "EVAL_RUN_CONFIG"
ENV_CONFIG_SHA256 = "EVAL_RUN_CONFIG_SHA256"

_BINDING_FIELDS = (
    "schema",
    "run_id",
    "approval_sha256",
    "identity_sha256",
    "labels_sha256",
    "case_count",
    "provider_base_url",
    "provider_model",
    "reasoning_effort",
    "max_provider_requests",
    "spend_bound",
    "ledger_path",
    "scope",
    "proof_public_key",
)


class GuardNotBound(GuardError):
    """A run configuration is present but no guard was bound before this request."""


class GuardDenied(GuardError):
    """The request does not match the approved origin or model; nothing was sent."""


def is_loopback_host(host: str | None) -> bool:
    """Match the loopback forms accepted by the actual socket transport."""
    if not isinstance(host, str):
        return False
    name = host.strip().lower().rstrip(".")
    if not name:
        return False
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        try:
            address = ipaddress.IPv4Address(socket.inet_aton(name))
        except OSError:
            return False
    if address.is_unspecified:
        return True
    if isinstance(address, ipaddress.IPv6Address):
        mapped = address.ipv4_mapped
        if mapped is not None:
            return mapped.is_loopback or mapped.is_unspecified
    return address.is_loopback


def scope_for(base_url: str) -> str:
    """A loopback upstream is a local fake: boundary evidence, never quality evidence."""
    return "local_fake" if is_loopback_host(urlsplit(base_url).hostname) else "provider"


def _approved_upstream(base_url: str, model: str) -> str:
    scope = scope_for(base_url)
    if scope == "provider" and (base_url != PROVIDER_BASE_URL or model != PROVIDER_MODEL):
        raise ApprovalError("upstream is outside the verified OpenRouter price profile")
    return scope


@dataclass(frozen=True)
class RunBinding:
    """The immutable run configuration the parent issues and the candidate loads."""

    run_id: str
    approval_sha256: str
    identity_sha256: str
    labels_sha256: str
    case_count: int
    provider_base_url: str
    provider_model: str
    reasoning_effort: str | None
    max_provider_requests: int
    ledger_path: str
    scope: str
    proof_public_key: str
    spend_bound: SpendBound

    @classmethod
    def from_approval(cls, approval: ServiceApproval, *, proof_public_key: str) -> RunBinding:
        """Derive the issued configuration, binding the one key that may sign this run."""
        if not is_hex64(proof_public_key):
            raise ApprovalError(
                "a run configuration binds the raw Ed25519 public key (32 bytes, lowercase hex) "
                "that the candidate signs its responses with"
            )
        run_id = f"run-{approval.approval_sha256[:16]}"
        return cls(
            run_id=run_id,
            approval_sha256=approval.approval_sha256,
            identity_sha256=approval.identity_sha256,
            labels_sha256=approval.labels_sha256,
            case_count=approval.case_count,
            provider_base_url=approval.provider_origin,
            provider_model=approval.provider_model,
            reasoning_effort=approval.reasoning_effort,
            max_provider_requests=approval.max_provider_requests,
            spend_bound=approval.spend_bound,
            ledger_path=str(Path(approval.ledger_root) / f"{run_id}.jsonl"),
            scope=_approved_upstream(approval.provider_origin, approval.provider_model),
            proof_public_key=proof_public_key,
        )

    def ledger(self) -> AttemptLedger:
        return AttemptLedger(
            Path(self.ledger_path),
            binding=LedgerBinding(
                run_id=self.run_id,
                config_sha256=self.config_sha256,
                approval_sha256=self.approval_sha256,
                max_attempts=self.max_provider_requests,
                model=self.provider_model,
                base_url=self.provider_base_url,
                spend_bound=self.spend_bound,
            ),
        )

    @property
    def config_sha256(self) -> str:
        return digest(self.bound())

    def bound(self) -> dict[str, Any]:
        """Exactly the fields the issued configuration's digest covers."""
        return {
            "schema": CONFIG_SCHEMA,
            "run_id": self.run_id,
            "approval_sha256": self.approval_sha256,
            "identity_sha256": self.identity_sha256,
            "labels_sha256": self.labels_sha256,
            "case_count": self.case_count,
            "provider_base_url": self.provider_base_url,
            "provider_model": self.provider_model,
            "reasoning_effort": self.reasoning_effort,
            "max_provider_requests": self.max_provider_requests,
            "spend_bound": self.spend_bound.payload(),
            "ledger_path": self.ledger_path,
            "scope": self.scope,
            "proof_public_key": self.proof_public_key,
        }

    def proof_fingerprint(self) -> str:
        """The identity of the signing key, as the ledger claim binds it through the config."""
        return hashlib.sha256(self.proof_public_key.encode()).hexdigest()

    def payload(self) -> dict[str, Any]:
        return {**self.bound(), "config_sha256": self.config_sha256}

    def write(self, path: Path) -> str:
        """Write the configuration atomically; a conflicting existing file is never replaced."""
        path = Path(path)
        rendered = json.dumps(self.payload(), indent=2, sort_keys=True) + "\n"
        if path.exists():
            if path.read_text(encoding="utf-8") == rendered:
                return self.config_sha256
            raise ApprovalError(
                f"{path} already holds a different run configuration; a run may not be "
                "re-bound in place"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".new")
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, path)
        return self.config_sha256

    @classmethod
    def load(cls, path: Path, *, expected_sha256: str) -> RunBinding:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ApprovalError(f"run configuration {path} is unreadable: {exc}") from exc
        if not isinstance(payload, dict):
            raise ApprovalError(f"run configuration {path} is not an object")
        problems: list[str] = []
        if payload.get("schema") != CONFIG_SCHEMA:
            problems.append("config_schema_invalid")
        if not is_hex64(payload.get("approval_sha256")):
            problems.append("config_approval_missing")
        if payload.get("scope") not in {"provider", "local_fake"}:
            problems.append("config_scope_invalid")
        if not is_hex64(payload.get("proof_public_key")):
            problems.append("config_proof_key_missing")
        if not str(payload.get("ledger_path") or "").strip():
            problems.append("config_ledger_missing")
        elif not Path(str(payload["ledger_path"])).is_absolute():
            problems.append("config_ledger_not_absolute")
        cap = payload.get("max_provider_requests")
        if type(cap) is not int or not 1 <= cap <= MAX_ATTEMPTS:
            problems.append("config_budget_invalid")
        if payload.get("reasoning_effort") != "none":
            problems.append("config_reasoning_invalid")
        spend: SpendBound | None = None
        try:
            spend = SpendBound.from_dict(payload.get("spend_bound"))
        except SpendError:
            problems.append("config_spend_bound_invalid")
        base_url = str(payload.get("provider_base_url") or "").rstrip("/")
        model = str(payload.get("provider_model") or "")
        try:
            expected_scope = _approved_upstream(base_url, model)
            if payload.get("scope") != expected_scope:
                problems.append("config_scope_mismatch")
        except ApprovalError:
            problems.append("config_upstream_unsupported")
        recorded = payload.get("config_sha256")
        computed = digest({key: payload.get(key) for key in _BINDING_FIELDS})
        if not is_hex64(recorded):
            problems.append("config_digest_missing")
        elif recorded != computed:
            problems.append("config_digest_mismatch")
        elif recorded != str(expected_sha256):
            problems.append("config_digest_not_announced")
        if problems:
            raise ApprovalError(
                f"run configuration {path} is not the issued binding: " + ", ".join(problems)
            )
        assert spend is not None
        return cls(
            run_id=str(payload["run_id"]),
            approval_sha256=str(payload["approval_sha256"]),
            identity_sha256=str(payload["identity_sha256"]),
            labels_sha256=str(payload["labels_sha256"]),
            case_count=int(payload["case_count"]),
            provider_base_url=base_url,
            provider_model=model,
            reasoning_effort="none",
            spend_bound=spend,
            max_provider_requests=int(payload["max_provider_requests"]),
            ledger_path=str(payload["ledger_path"]),
            scope=str(payload["scope"]),
            proof_public_key=str(payload["proof_public_key"]),
        )


def issue_run_binding(approval: ServiceApproval) -> tuple[RunBinding, RunProofKey]:
    """Issue one run configuration and the per-run key pair that may sign for it.

    The parent holds this key pair in memory for the life of the run. The private half goes
    to the candidate's environment and nowhere else.
    """
    key = generate_keypair()
    return RunBinding.from_approval(approval, proof_public_key=key.public_key), key


class RunGuard:
    """Admits one attempt per real provider request, or fails before the network."""

    def __init__(self, binding: RunBinding, ledger: AttemptLedger) -> None:
        self.binding = binding
        self.ledger = ledger

    def record_claim(self) -> int:
        return self.ledger.claim()

    def prepare(self, body: dict[str, Any]) -> None:
        self.binding.spend_bound.prepare(body)

    def admit(self, *, stage: str, model: str, base_url: str, request: bytes) -> int:
        origin = base_url.rstrip("/")
        if model != self.binding.provider_model:
            self.ledger.refuse(reason="model_not_approved", model=model, base_url=origin)
            raise GuardDenied("model is not approved; request never left this process")
        if origin != self.binding.provider_base_url:
            self.ledger.refuse(reason="origin_not_approved", model=model, base_url=origin)
            raise GuardDenied("origin is not approved; request never left this process")
        try:
            output_limit = self.binding.spend_bound.validate_request(request, model=model)
        except SpendError as exc:
            self.ledger.refuse(reason="request_outside_spend_profile", model=model, base_url=origin)
            raise GuardDenied(str(exc)) from exc
        return self.ledger.admit(
            stage=stage,
            model=model,
            base_url=origin,
            request_sha256=hashlib.sha256(request).hexdigest(),
            output_limit=output_limit,
        )

    def settle(self, seq: int, usage: Any) -> bool:
        return self.ledger.settle(seq, usage)


_guard: RunGuard | None = None


def build_guard(binding: RunBinding) -> RunGuard:
    return RunGuard(binding, binding.ledger())


def bind_run_guard(environ: Mapping[str, str] | None = None) -> RunGuard:
    """Bind the issued run configuration and leave its durable claim. Startup only."""
    global _guard
    source = os.environ if environ is None else environ
    path = str(source.get(ENV_CONFIG) or "").strip()
    announced = str(source.get(ENV_CONFIG_SHA256) or "").strip()
    if not path:
        raise GuardNotBound(
            f"{ENV_CONFIG} is unset; a service candidate binds an approved run before readiness"
        )
    if not announced:
        raise GuardNotBound(f"{ENV_CONFIG_SHA256} is unset; the run configuration is unverified")
    guard = build_guard(RunBinding.load(Path(path), expected_sha256=announced))
    if _guard is not None and _guard.binding.config_sha256 != guard.binding.config_sha256:
        raise GuardError(
            "this process already bound run "
            f"{_guard.binding.run_id}; one process serves one approved run"
        )
    guard.record_claim()
    _guard = guard
    return guard


def current_run_guard() -> RunGuard | None:
    return _guard


def require_run_guard() -> RunGuard | None:
    """The single HTTP boundary check: a bound guard, or ordinary production with none."""
    guard = _guard
    if guard is not None:
        return guard
    if str(os.environ.get(ENV_CONFIG) or "").strip():
        raise GuardNotBound(
            f"{ENV_CONFIG} is set but no guard was bound at startup; refusing to send an "
            "unbounded provider request"
        )
    return None


__all__ = [
    "CONFIG_SCHEMA",
    "ENV_CONFIG",
    "ENV_CONFIG_SHA256",
    "GuardDenied",
    "GuardNotBound",
    "RunBinding",
    "RunGuard",
    "bind_run_guard",
    "build_guard",
    "current_run_guard",
    "is_loopback_host",
    "issue_run_binding",
    "require_run_guard",
    "scope_for",
]
