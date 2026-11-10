"""The approval surface of a bounded service evaluation run.

An approval is written once, by the operator, from an intent that names the
approver, the timestamp, the exact provider origin and model, and the exact
maximum number of upstream attempts. This module seals that intent against the
loaded evaluation identity, verifies an issued approval before anything starts,
issues the run configuration, proves the candidate's durable claim before the
first POST, and attests the sealed attempt ledger afterwards. It never approves
anything by itself and never invents a cap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from app.evaluation import narrative_cli
from app.evaluation.attempt_ledger import (
    Attestation,
    LedgerError,
    attest,
)
from app.evaluation.candidate_identity import candidate_identity
from app.evaluation.candidate_proof import RunProofKey
from app.evaluation.labels import (
    LabelSet,
    evaluation_identity,
    identity_digest,
    load_labels,
)
from app.evaluation.mapping import load_documents, load_mapping
from app.evaluation.provider_approval import (
    DEFAULT_LEDGER_ROOT,
    ApprovalError,
    ServiceApproval,
    approval_payload,
    load_approval,
)
from app.evaluation.provider_funding import FundingError, verify_provider_funding
from app.evaluation.provider_guard import RunBinding, issue_run_binding
from app.evaluation.spend_bound import MAX_ATTEMPTS, SpendBound, SpendError
from eval_process import (
    ARTIFACTS,
    DEFAULT_REDIS_URL,
    PROVIDER_KEY_ENV,
    RunnerFailure,
    ServiceSettings,
    validate_redis_url,
)

APPROVAL_INTENT_FIELDS = (
    "approved",
    "approver",
    "approved_at",
    "provider_base_url",
    "provider_model",
    "max_provider_requests",
    "reasoning_effort",
    "spend_bound",
)


def evaluation_identity_of(
    args: argparse.Namespace, *, questions: Path, expectations: Path
) -> tuple[str, LabelSet]:
    """The exact identity an approval must bind: labels, mapping and documents."""
    labels = load_labels(questions, expectations)
    mapping = load_mapping(Path(args.mapping).expanduser().resolve())
    documents_sha256: str | None = None
    if args.documents is not None:
        documents = Path(args.documents).expanduser().resolve()
        load_documents(documents, mapping)
        documents_sha256 = hashlib.sha256(documents.read_bytes()).hexdigest()
    identity = evaluation_identity(
        labels,
        mapping_sha256=mapping.file_sha256,
        documents_sha256=documents_sha256,
        narrative_sha256=narrative_cli.labels_digest(args),
    )
    narrative_cli.load(args, primary_identity_sha256=identity_digest(identity))
    return identity_digest(identity), labels


def prepare_approval(
    args: argparse.Namespace,
    approval_path: Path,
    *,
    questions: Path,
    expectations: Path,
) -> int:
    """Seal the operator's intent into an approval artifact. Never approves anything itself."""
    try:
        intent = json.loads(Path(args.prepare_approval).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerFailure(f"approval intent is unreadable: {exc}") from exc
    if not isinstance(intent, dict):
        raise RunnerFailure("approval intent is not an object")
    missing = [field for field in APPROVAL_INTENT_FIELDS if field not in intent]
    if missing:
        raise RunnerFailure(
            "the approval intent must state " + ", ".join(missing) + " explicitly; "
            "an approval is never inferred"
        )
    if approval_path.exists():
        raise RunnerFailure(f"{approval_path} already exists; an approval is never rewritten")
    identity_sha256, labels = evaluation_identity_of(
        args, questions=questions, expectations=expectations
    )
    try:
        candidate = candidate_identity()
    except (OSError, RuntimeError) as exc:
        raise RunnerFailure("cannot identify candidate worktree") from exc
    cap = intent["max_provider_requests"]
    if type(cap) is not int or not 1 <= cap <= MAX_ATTEMPTS:
        raise RunnerFailure("intent max_provider_requests is invalid")
    if intent["reasoning_effort"] != "none":
        raise RunnerFailure("the approved evaluation requires reasoning disabled")
    try:
        spend = SpendBound.from_dict(intent["spend_bound"])
    except SpendError as exc:
        raise RunnerFailure(f"spend bound is invalid: {exc}") from exc
    payload = approval_payload(
        approved=intent["approved"] is True,
        approver=str(intent["approver"]),
        approved_at=str(intent["approved_at"]),
        identity_sha256=identity_sha256,
        candidate=candidate,
        labels_sha256=labels.labels_sha256,
        case_count=labels.case_count,
        provider_base_url=str(intent["provider_base_url"]),
        provider_model=str(intent["provider_model"]),
        max_provider_requests=cap,
        ledger_root=str(intent.get("ledger_root") or DEFAULT_LEDGER_ROOT),
        reasoning_effort="none",
        spend_bound=spend,
    )
    approval_path.parent.mkdir(parents=True, exist_ok=True)
    approval_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "approval": os.path.relpath(approval_path, Path.cwd()),
                "approved": payload["approved"],
                "identity_sha256": identity_sha256,
                "candidate": candidate,
                "case_count": labels.case_count,
                "budget_sha256": payload["budget_sha256"],
                "note": "prepared from the operator's intent; this run authorised nothing",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def service_settings(
    args: argparse.Namespace,
    *,
    approval_path: Path,
    output: Path,
    questions: Path,
    expectations: Path,
) -> tuple[ServiceSettings, ServiceApproval, RunProofKey]:
    """Verify the approval against the loaded identity and issue the run configuration.

    The per-run Ed25519 key pair is generated here, in this process's memory. Its public
    half is written into the configuration, so the configuration digest and the attempt
    ledger's claim cover it. Its private half is returned to the caller and handed to the
    candidate process through its environment only.
    """
    identity_sha256, labels = evaluation_identity_of(
        args, questions=questions, expectations=expectations
    )
    try:
        candidate = candidate_identity()
    except (OSError, RuntimeError) as exc:
        raise RunnerFailure("cannot identify candidate worktree") from exc
    try:
        approval = load_approval(
            approval_path,
            identity_sha256=identity_sha256,
            candidate=candidate,
            labels_sha256=labels.labels_sha256,
            case_count=labels.case_count,
        )
    except ApprovalError as exc:
        raise RunnerFailure(str(exc)) from exc
    key_variable = args.provider_key_env or PROVIDER_KEY_ENV
    api_key = os.environ.get(key_variable, "").strip()
    if not api_key:
        raise RunnerFailure(
            f"{key_variable} is empty; a service run takes the provider key from the "
            "operator's environment and never from .env or the artifacts"
        )
    try:
        verify_provider_funding(approval.provider_origin, api_key)
    except FundingError as exc:
        raise RunnerFailure(str(exc)) from exc
    redis_url = validate_redis_url(args.redis_url or DEFAULT_REDIS_URL)
    binding, proof_key = issue_run_binding(approval)
    config_path = output / ARTIFACTS["run_config"]
    try:
        binding.write(config_path)
    except ApprovalError as exc:
        raise RunnerFailure(str(exc)) from exc
    approval.write(output / ARTIFACTS["approval"])
    return ServiceSettings(binding, api_key, redis_url, config_path), approval, proof_key


def require_claim(binding: RunBinding) -> None:
    """Verify the exact guarded spend authority before the first analyst POST."""
    try:
        current = binding.ledger().snapshot()
    except (LedgerError, OSError) as exc:
        raise RunnerFailure(str(exc)) from exc
    if current.claim is None or current.sealed:
        raise RunnerFailure("candidate has no live claimed budget")


def seal_and_attest(binding: RunBinding) -> Attestation:
    ledger = binding.ledger()
    try:
        ledger.seal()
    except (LedgerError, OSError) as exc:
        raise RunnerFailure(f"the budget ledger could not be sealed: {exc}") from exc
    return attest(ledger, require_sealed=True)
