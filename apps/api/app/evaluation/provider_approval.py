"""Content-bound authorization for one attempt- and dollar-limited service run.

The approval binds the full evaluation identity, exact origin/model and the verified
price profile. Full-context reservations and validated usage settlements enforce its
aggregate upper-cost limit before every upstream request.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.evaluation.spend_bound import MAX_ATTEMPTS, SpendBound, SpendError

APPROVAL_SCHEMA = "evaluation-budget-approval-v4"
APPROVAL_PURPOSE = "bounded-service-evaluation"
DEFAULT_LEDGER_ROOT = "~/.knicksiq/eval-ledger"
CAP_CEILING = MAX_ATTEMPTS

_APPROVAL_FIELDS = (
    "schema",
    "purpose",
    "approved",
    "approver",
    "approved_at",
    "identity_sha256",
    "candidate",
    "labels_sha256",
    "case_count",
    "provider_base_url",
    "provider_model",
    "reasoning_effort",
    "max_provider_requests",
    "spend_bound",
    "ledger_root",
)


class GuardError(RuntimeError):
    """A provider request could not be admitted under an approved run."""


class ApprovalError(GuardError):
    """The approval artifact does not authorize a bounded run."""


def digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def is_hex64(value: Any) -> bool:
    """A digest or a raw Ed25519 public key is exactly 64 lowercase hex characters."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _origin(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApprovalError("the approval must bind the exact provider base URL")
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ApprovalError(f"{value!r} is not an absolute HTTP provider base URL")
    if parts.query or parts.fragment:
        raise ApprovalError(f"{value!r} carries a query or fragment; bind an origin only")
    return value.strip().rstrip("/")


def _timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ApprovalError("the approval needs a named approval timestamp")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApprovalError(f"approval timestamp {text!r} is not ISO 8601") from exc
    return text


@dataclass(frozen=True)
class ServiceApproval:
    """The operator's bounded-run approval, verified against the loaded artifacts."""

    approver: str
    approved_at: str
    identity_sha256: str
    candidate: dict[str, Any]
    labels_sha256: str
    case_count: int
    provider_base_url: str
    provider_model: str
    reasoning_effort: str | None
    max_provider_requests: int
    ledger_root: str
    spend_bound: SpendBound
    budget_sha256: str
    artifact: dict[str, Any]

    @property
    def approval_sha256(self) -> str:
        return self.budget_sha256

    @property
    def provider_origin(self) -> str:
        """The bound origin without a trailing slash: what a request must match exactly."""
        return self.provider_base_url.strip().rstrip("/")

    def payload(self) -> dict[str, Any]:
        """The artifact exactly as it was approved; a copy never re-interprets a field."""
        return dict(self.artifact)

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(self.payload(), indent=2, sort_keys=True) + "\n"
        path.write_text(rendered, encoding="utf-8")
        return path


def approval_payload(
    *,
    approver: str,
    approved_at: str,
    identity_sha256: str,
    candidate: dict[str, Any],
    labels_sha256: str,
    case_count: int,
    provider_base_url: str,
    provider_model: str,
    reasoning_effort: str,
    max_provider_requests: int,
    spend_bound: SpendBound,
    ledger_root: str = DEFAULT_LEDGER_ROOT,
    approved: bool = False,
) -> dict[str, Any]:
    """Build the approval artifact the operator signs: every bound field, one digest."""
    bound: dict[str, Any] = {
        "schema": APPROVAL_SCHEMA,
        "purpose": APPROVAL_PURPOSE,
        "approved": bool(approved),
        "approver": str(approver or ""),
        "approved_at": str(approved_at or ""),
        "identity_sha256": str(identity_sha256),
        "candidate": candidate,
        "labels_sha256": str(labels_sha256),
        "case_count": case_count,
        "provider_base_url": str(provider_base_url or ""),
        "provider_model": str(provider_model or ""),
        "reasoning_effort": reasoning_effort,
        "max_provider_requests": max_provider_requests,
        "spend_bound": spend_bound.payload(),
        "ledger_root": str(ledger_root),
    }
    return {**bound, "budget_sha256": digest(bound)}


def _approval_problems(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["approval_not_artifact"]
    problems: list[str] = []
    if payload.get("schema") != APPROVAL_SCHEMA:
        problems.append("approval_schema_invalid")
    if payload.get("purpose") != APPROVAL_PURPOSE:
        problems.append("approval_purpose_invalid")
    if payload.get("approved") is not True:
        problems.append("approval_not_approved")
    if not str(payload.get("approver") or "").strip():
        problems.append("approval_approver_missing")
    try:
        _timestamp(payload.get("approved_at"))
    except ApprovalError:
        problems.append("approval_timestamp_invalid")
    if not is_hex64(payload.get("identity_sha256")):
        problems.append("approval_identity_missing")
    candidate = payload.get("candidate")
    if (
        not isinstance(candidate, dict)
        or set(candidate) != {"commit", "source_sha256", "dirty"}
        or not isinstance(candidate.get("commit"), str)
        or len(candidate["commit"]) not in (40, 64)
        or any(c not in "0123456789abcdef" for c in candidate["commit"])
        or not is_hex64(candidate.get("source_sha256"))
        or type(candidate.get("dirty")) is not bool
    ):
        problems.append("approval_candidate_invalid")
    if not is_hex64(payload.get("labels_sha256")):
        problems.append("approval_labels_missing")
    cases = payload.get("case_count")
    if isinstance(cases, bool) or not isinstance(cases, int) or cases <= 0:
        problems.append("approval_case_count_invalid")
    try:
        _origin(payload.get("provider_base_url"))
    except ApprovalError:
        problems.append("approval_base_url_invalid")
    if not str(payload.get("provider_model") or "").strip():
        problems.append("approval_model_missing")
    if payload.get("reasoning_effort") != "none":
        problems.append("approval_reasoning_effort_invalid")
    cap = payload.get("max_provider_requests")
    if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
        problems.append("approval_budget_invalid")
    elif cap > CAP_CEILING:
        problems.append("approval_budget_above_ceiling")
    try:
        SpendBound.from_dict(payload.get("spend_bound"))
    except SpendError:
        problems.append("approval_spend_bound_invalid")
    root = payload.get("ledger_root")
    if not isinstance(root, str) or not Path(root).expanduser().is_absolute():
        problems.append("approval_ledger_root_not_absolute")
    recorded = payload.get("budget_sha256")
    if not is_hex64(recorded):
        problems.append("approval_digest_missing")
    elif recorded != digest({key: payload.get(key) for key in _APPROVAL_FIELDS}):
        problems.append("approval_digest_mismatch")
    return problems


def load_approval(
    path: Path,
    *,
    identity_sha256: str,
    candidate: dict[str, Any],
    labels_sha256: str,
    case_count: int,
) -> ServiceApproval:
    """Read an approval and require it to bind this exact evaluation identity."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApprovalError(f"approval artifact {path} is unreadable: {exc}") from exc
    problems = _approval_problems(payload)
    if not problems:
        if payload["identity_sha256"] != identity_sha256:
            problems.append("approval_identity_mismatch")
        if payload["candidate"] != candidate:
            problems.append("approval_candidate_mismatch")
        if payload["labels_sha256"] != labels_sha256:
            problems.append("approval_labels_mismatch")
        if payload["case_count"] != case_count:
            problems.append("approval_case_count_mismatch")
    if problems:
        raise ApprovalError(
            f"approval artifact {path} does not authorize this run: " + ", ".join(problems)
        )
    return ServiceApproval(
        approver=str(payload["approver"]).strip(),
        approved_at=_timestamp(payload["approved_at"]),
        identity_sha256=str(payload["identity_sha256"]),
        candidate=dict(payload["candidate"]),
        labels_sha256=str(payload["labels_sha256"]),
        case_count=int(payload["case_count"]),
        provider_base_url=str(payload["provider_base_url"]).strip(),
        provider_model=str(payload["provider_model"]).strip(),
        reasoning_effort=payload["reasoning_effort"],
        max_provider_requests=int(payload["max_provider_requests"]),
        ledger_root=str(Path(str(payload["ledger_root"])).expanduser()),
        spend_bound=SpendBound.from_dict(payload["spend_bound"]),
        budget_sha256=str(payload["budget_sha256"]),
        artifact=dict(payload),
    )


__all__ = [
    "APPROVAL_PURPOSE",
    "APPROVAL_SCHEMA",
    "CAP_CEILING",
    "DEFAULT_LEDGER_ROOT",
    "ApprovalError",
    "GuardError",
    "ServiceApproval",
    "approval_payload",
    "digest",
    "is_hex64",
    "load_approval",
]
