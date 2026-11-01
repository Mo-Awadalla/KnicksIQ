"""Request-correlated collection against a candidate API.

Collecting is separated from scoring: every record stores the exact request,
turn id, revision, response and its digest, so a score can be recomputed later
and an observation cannot be replaced by a second, unrecorded search.

Collection is local-only and provider-free for the ``disabled`` profile:

- the candidate must be a loopback HTTP endpoint, so the collector cannot emit
  outbound traffic or follow a redirect off loopback;
- ambient proxy settings are never consulted and redirects are refused;
- the ``disabled`` profile asserts what it did not do: the run aborts at the
  first response that reports a model stage, and the summary refuses to
  publish a provider-free claim.

The ``service`` profile is the enabled path. It never carries an approval of its
own: it loads the run configuration the operator's approval produced, proves
before the first analyst POST that a guarded candidate process claimed that exact
configuration in its attempt ledger, stamps every response with the run identity,
and reports upstream attempts from the ledger separately from the logical model
stages the candidate reports.

The wire exchange itself lives in :mod:`app.evaluation.collection_transport`;
this module decides what a run means and what evidence it may publish.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.evaluation.attempt_ledger import LedgerError
from app.evaluation.candidate_proof import (
    PREFLIGHT_PATH,
    PROOF_HEADER,
    ProofError,
    ResponseProof,
    canonical_digest,
    challenge_payload,
    new_nonce,
)
from app.evaluation.collection_transport import (
    RunnerError,
    collect_case,
    count_provider_stages,
    direct_opener,
    validate_base_url,
)
from app.evaluation.labels import ExpectationCase
from app.evaluation.provider_approval import ApprovalError
from app.evaluation.provider_guard import RunBinding, RunGuard, build_guard
from app.evaluation.run_stamp import RunStamp

Profile = Literal["disabled", "service"]


@dataclass(frozen=True)
class CollectionSummary:
    profile: Profile
    cases_requested: int
    cases_recorded: int
    http_errors: int
    provider_stages: int
    base_url: str
    provider_attempts: int = 0
    attempts_refused: int = 0
    run_id: str | None = None
    scope: str | None = None
    proofs_verified: int = 0


def _approved_binding(run_config: Path | None, announced: str) -> RunBinding:
    if run_config is None:
        raise RunnerError(
            "the service profile needs --run-config: the run configuration issued for the "
            "operator's approval, plus the digest that was announced with it"
        )
    if not announced.strip():
        raise RunnerError(
            "the service profile needs --run-config-sha256, the digest announced with the "
            "run configuration; an unverified binding authorizes nothing"
        )
    try:
        return RunBinding.load(run_config, expected_sha256=announced.strip())
    except ApprovalError as exc:
        raise RunnerError(str(exc)) from exc


def _prove_guard(binding: RunBinding) -> RunGuard:
    """Prove before the first analyst POST that a guarded process bound this exact run."""
    guard = build_guard(binding)
    try:
        records = guard.ledger.records()
    except LedgerError as exc:
        raise RunnerError(f"the attempt ledger cannot be read: {exc}") from exc
    if not records:
        raise RunnerError(
            f"no guarded candidate ever claimed run {binding.run_id}: "
            f"{binding.ledger_path} holds no record, so a provider request from this run "
            "would be unmetered and collection is refused"
        )
    if not any(
        record.kind == "claim" and record.config_sha256 == binding.config_sha256
        for record in records
    ):
        raise RunnerError(
            f"the attempt ledger for run {binding.run_id} carries no claim for run "
            f"configuration {binding.config_sha256}; the candidate on {binding.scope} "
            "was not bound to this run and its attempts are not this run's attempts"
        )
    if guard.ledger.sealed:
        raise RunnerError(
            f"the attempt ledger for run {binding.run_id} is sealed; the approved run is "
            "closed and needs a new approval"
        )
    if guard.ledger.used >= binding.max_provider_requests:
        raise RunnerError(
            f"run {binding.run_id} already admitted {guard.ledger.used} of "
            f"{binding.max_provider_requests} approved provider attempts"
        )
    return guard


def _bound_labels(binding: RunBinding, labels_sha256: str, case_count: int) -> None:
    if binding.labels_sha256 != labels_sha256:
        raise RunnerError(
            f"the run configuration binds labels {binding.labels_sha256}, not the loaded "
            f"labels {labels_sha256}"
        )
    if binding.case_count != case_count:
        raise RunnerError(
            f"the run configuration binds {binding.case_count} cases, not the loaded {case_count}"
        )


def _proof_problems(
    proof: ResponseProof,
    binding: RunBinding,
    *,
    kind: str,
    nonce: str,
    request: dict[str, Any],
    status: int,
    response_sha256: str,
) -> list[str]:
    """Everything one proof must state to be this run's answer to this exact request."""
    problems: list[str] = []
    if proof.kind != kind:
        problems.append("proof_kind_mismatch")
    if proof.run_id != binding.run_id:
        problems.append("proof_run_mismatch")
    if proof.approval_sha256 != binding.approval_sha256:
        problems.append("proof_approval_mismatch")
    if proof.config_sha256 != binding.config_sha256:
        problems.append("proof_config_mismatch")
    if proof.scope != binding.scope:
        problems.append("proof_scope_mismatch")
    if not nonce or proof.nonce != nonce:
        problems.append("proof_nonce_mismatch")
    if proof.request_sha256 != canonical_digest(request):
        problems.append("proof_request_mismatch")
    if proof.http_status != status:
        problems.append("proof_status_mismatch")
    if proof.response_sha256 != response_sha256:
        problems.append("proof_response_mismatch")
    try:
        proof.verify(binding.proof_public_key)
    except ProofError:
        problems.append("proof_signature_invalid")
    return problems


def prove_candidate(base_url: str, binding: RunBinding, *, timeout: float) -> dict[str, Any]:
    """Prove a live, bound candidate before the first analyst POST spends anything."""
    nonce = new_nonce()
    challenge = challenge_payload(
        nonce=nonce,
        run_id=binding.run_id,
        config_sha256=binding.config_sha256,
        scope=binding.scope,
    )
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{PREFLIGHT_PATH}",
        data=json.dumps(challenge).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with direct_opener().open(request, timeout=timeout) as response:
            status = int(response.status)
            raw = response.read()
            header = response.headers.get(PROOF_HEADER) or ""
    except urllib.error.HTTPError as exc:
        raise RunnerError(
            f"the candidate refused the preflight challenge with HTTP {exc.code}; only the "
            "bound evaluation entrypoint answers it, and nothing was sent to a provider"
        ) from exc
    except RunnerError:
        raise
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RunnerError(
            f"the candidate never answered the preflight challenge ({type(exc).__name__}); "
            "without a live proof before the first analyst request nothing may be collected"
        ) from exc
    if not header:
        raise RunnerError(
            "the candidate answered the preflight challenge without a proof; it is not the "
            "evaluation entrypoint bound to this run"
        )
    try:
        proof = ResponseProof.from_header(header)
    except ProofError as exc:
        raise RunnerError(f"the preflight proof is unreadable: {exc}") from exc
    try:
        answered = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise RunnerError("the preflight answer is not JSON") from exc
    if not isinstance(answered, dict):
        raise RunnerError("the preflight answer is not an object")
    problems = _proof_problems(
        proof,
        binding,
        kind="preflight",
        nonce=nonce,
        request=challenge,
        status=status,
        response_sha256=canonical_digest(answered),
    )
    if problems:
        raise RunnerError("the preflight proof does not bind this run: " + ", ".join(problems))
    for name, value in (
        ("run_id", binding.run_id),
        ("config_sha256", binding.config_sha256),
        ("scope", binding.scope),
    ):
        if answered.get(name) != value:
            raise RunnerError(f"the preflight answer describes a different {name}")
    if answered.get("nonce") != nonce:
        raise RunnerError("the preflight answer answers a different challenge nonce")
    return {"nonce": nonce, "sequence": proof.sequence, "proof": proof.as_dict()}


def verify_record_proof(record: dict[str, Any], binding: RunBinding) -> ResponseProof:
    """Refuse one collected record unless the candidate itself signed exactly this exchange."""
    case_id = str(record.get("case_id") or "")
    try:
        proof = ResponseProof.from_record(record)
    except ProofError as exc:
        raise RunnerError(f"the candidate proof for case {case_id} is unreadable: {exc}") from exc
    if proof is None:
        detail = str(record.get("proof_problem") or "").strip()
        raise RunnerError(
            f"case {case_id} carries no candidate proof"
            + (f" ({detail})" if detail else "")
            + "; a collector-written record is not service evidence"
        )
    problems = _proof_problems(
        proof,
        binding,
        kind="response",
        nonce=str(record.get("challenge") or ""),
        request=record.get("request") or {},
        status=int(record.get("http_status") or 0),
        response_sha256=canonical_digest(record.get("response") or {}),
    )
    if problems:
        raise RunnerError(
            f"the candidate proof for case {case_id} is rejected: " + ", ".join(problems)
        )
    return proof


def collect(
    cases: list[ExpectationCase],
    *,
    base_url: str,
    profile: Profile,
    timeout: float,
    season: str,
    limit: int | None = None,
    labels_sha256: str = "",
    run_config: Path | None = None,
    run_config_sha256: str = "",
) -> tuple[list[dict[str, Any]], CollectionSummary]:
    validate_base_url(base_url)
    if profile not in {"disabled", "service"}:
        raise RunnerError(f"unknown collection profile {profile!r}")
    if profile == "disabled":
        if run_config is not None or run_config_sha256.strip():
            raise RunnerError(
                "a run configuration belongs to the service profile; a disabled run is "
                "provider-free and binds no attempt ledger"
            )
    else:
        binding = _approved_binding(run_config, run_config_sha256)
        _bound_labels(binding, labels_sha256, len(cases))
        if limit is not None:
            raise RunnerError(
                "an approved run collects its whole identity: --limit would leave "
                f"{len(cases)} approved cases unobserved"
            )
        guard = _prove_guard(binding)
        # Prove the candidate before the first analyst POST: a bound entrypoint answers a
        # signed challenge without touching a provider, so an unprovable candidate is
        # rejected before any paid request exists to regret.
        prove_candidate(base_url, binding, timeout=timeout)
        records, stages = _collect_all(
            cases,
            base_url=base_url,
            season=season,
            timeout=timeout,
            limit=None,
            stop_on_stages=False,
            binding=binding,
        )
        stamp = RunStamp(
            run_id=binding.run_id,
            approval_sha256=binding.approval_sha256,
            config_sha256=binding.config_sha256,
            scope=binding.scope,
        ).as_dict()
        for record in records:
            record["run"] = stamp
        try:
            attempts = guard.ledger.used
            sealed = guard.ledger.sealed
            refused = sum(1 for record in guard.ledger.records() if record.kind == "refused")
        except LedgerError as exc:
            raise RunnerError(f"the attempt ledger became unreadable: {exc}") from exc
        if sealed:
            raise RunnerError(
                f"the attempt ledger for run {binding.run_id} was sealed during collection"
            )
        return records, CollectionSummary(
            profile=profile,
            cases_requested=len(cases),
            cases_recorded=len(records),
            http_errors=sum(1 for record in records if record["http_status"] != 200),
            provider_stages=stages,
            base_url=base_url,
            provider_attempts=attempts,
            attempts_refused=refused,
            run_id=binding.run_id,
            scope=binding.scope,
            proofs_verified=len(records),
        )
    records, stages = _collect_all(
        cases,
        base_url=base_url,
        season=season,
        timeout=timeout,
        limit=limit,
        stop_on_stages=True,
    )
    return records, CollectionSummary(
        profile=profile,
        cases_requested=len(cases[:limit] if limit else cases),
        cases_recorded=len(records),
        http_errors=sum(1 for record in records if record["http_status"] != 200),
        provider_stages=stages,
        base_url=base_url,
    )


def _collect_all(
    cases: list[ExpectationCase],
    *,
    base_url: str,
    season: str,
    timeout: float,
    limit: int | None,
    stop_on_stages: bool,
    binding: RunBinding | None = None,
) -> tuple[list[dict[str, Any]], int]:
    selected = cases[:limit] if limit else cases
    records: list[dict[str, Any]] = []
    stages = 0
    for case in selected:
        challenge = new_nonce() if binding is not None else ""
        record = collect_case(base_url, case, season=season, timeout=timeout, challenge=challenge)
        if binding is not None:
            # Verified before the record is kept: an unproven answer stops the run rather
            # than joining the submission and borrowing another record's evidence.
            verify_record_proof(record, binding)
        records.append(record)
        stages += count_provider_stages(record)
        if stop_on_stages and stages:
            # Stop at the first model stage: the disabled profile must not keep spending
            # requests once its own provider-free claim is already false.
            raise RunnerError(
                f"{stages} model stages reported under the disabled profile after "
                f"{len(records)} of {len(selected)} cases; zero provider requests cannot "
                "be claimed and no further requests are sent"
            )
    return records, stages


__all__ = [
    "CollectionSummary",
    "Profile",
    "prove_candidate",
    "collect",
    "verify_record_proof",
]
