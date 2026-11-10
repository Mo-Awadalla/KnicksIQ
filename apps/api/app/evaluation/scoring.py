"""Fail-closed scoring with fixed denominators and explicit, disaggregated gates.

Every original case is scored. Missing reviews, unapproved labels and absent
document-level narrative observations block their gates explicitly.

The ``disabled`` profile blocks on any model stage, so no report can present a
paying run as a deterministic measurement. The ``service`` profile is accepted
only with a verified approved-run binding, a persisted attempt attestation, and
a candidate-signed proof on every single observation, checkable offline from the
public key bound in the run configuration. It reports upstream attempts from the
ledger separately from the logical model stages the responses report and never
compares them. A loopback fake wire keeps its ``local_fake`` proof scope and
blocks as quality evidence: it proves boundary behaviour, never quality.
"""

from __future__ import annotations

from typing import Any

from app.evaluation.assertion_checks import AssertionFailure
from app.evaluation.attempt_ledger import Attestation
from app.evaluation.candidate_proof import ProofError, canonical_digest
from app.evaluation.labels import LabelSet
from app.evaluation.mapping import RuntimeMapping
from app.evaluation.observations import Submission
from app.evaluation.provider_guard import RunBinding
from app.evaluation.reviews import DecisionRecord
from app.evaluation.scoring_cases import CaseScore, score_case
from app.evaluation.scoring_metrics import (
    _gates,
    _observed,
    answer_metrics,
    disposition_metrics,
    latency_entries,
    review_metrics,
    semantic_metrics,
)

SCHEMA = "evaluation-report-v3"


def _label_blockers(labels: LabelSet) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if labels.owner_approved < labels.case_count:
        blockers.append(
            {
                "code": "labels_owner_unapproved",
                "detail": f"{labels.case_count - labels.owner_approved} of {labels.case_count} "
                "cases have no owner approval",
            }
        )
    if not labels.frozen:
        blockers.append({"code": "labels_not_frozen", "detail": "no freeze manifest"})
    if labels.labels_digest_status != "verified":
        blockers.append(
            {
                "code": "labels_digest_unverified",
                "detail": "recorded labels_sha256 matches no available artifact",
            }
        )
    if labels.freeze_problems:
        blockers.append(
            {
                "code": "labels_freeze_unverified",
                "detail": "; ".join(labels.freeze_problems),
            }
        )
    if labels.approval_problems:
        blockers.append(
            {
                "code": "labels_approval_unverified",
                "detail": "; ".join(labels.approval_problems),
            }
        )
    return blockers


def _submission_blockers(
    submission: Submission,
    *,
    profile: str,
    missing_cases: list[str],
    duplicates: list[str],
    unknown_cases: list[str],
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if missing_cases:
        blockers.append(
            {"code": "cases_missing", "detail": f"{len(missing_cases)} cases have no response"}
        )
    if duplicates:
        blockers.append(
            {"code": "duplicate_observation", "detail": f"{len(duplicates)} duplicate responses"}
        )
    if unknown_cases:
        blockers.append(
            {
                "code": "unknown_case_observation",
                "detail": f"{len(unknown_cases)} responses do not belong to the dataset",
            }
        )
    if profile == "disabled":
        if submission.provider_requests:
            blockers.append(
                {
                    "code": "provider_requests_observed",
                    "detail": f"{submission.provider_requests} model stages reported under a "
                    "provider-free profile",
                }
            )
        if submission.run is not None:
            blockers.append(
                {
                    "code": "run_stamp_under_disabled_profile",
                    "detail": "a provider-free profile cannot record an approved-run identity",
                }
            )
    return blockers


def _service_blockers(
    submission: Submission,
    *,
    binding: RunBinding | None,
    attestation: Attestation | None,
) -> list[dict[str, str]]:
    """Service evidence needs the meter, not a boolean: run identity, admissions and seal."""
    blockers: list[dict[str, str]] = []
    if binding is None:
        return [
            {
                "code": "service_guard_unverified",
                "detail": "the service profile needs --run-config and its announced digest; "
                "without the approved run no attempt ledger can be verified",
            }
        ]
    if attestation is None:
        blockers.append(
            {"code": "service_guard_unattested", "detail": "no attestation was produced"}
        )
    elif not attestation.ok:
        blockers.append(
            {
                "code": "service_guard_unattested",
                "detail": "; ".join(attestation.problems),
            }
        )
    if not submission.provider_requests:
        blockers.append(
            {
                "code": "service_stages_absent",
                "detail": "no model stage was reported; a deterministic run is not service "
                "evidence even when an attempt ledger exists",
            }
        )
    if binding.scope == "local_fake":
        blockers.append(
            {
                "code": "service_evidence_local_fake",
                "detail": "the approved upstream was a loopback fake: this proves boundary "
                "behaviour only, never provider quality",
            }
        )
    if attestation is not None and attestation.ok and not attestation.admitted:
        blockers.append(
            {
                "code": "service_attempts_absent",
                "detail": "no upstream attempt was admitted; this run did not exercise a provider",
            }
        )
    return blockers


def _service_proof_blockers(
    submission: Submission, binding: RunBinding | None
) -> tuple[list[dict[str, str]], dict[str, int], dict[str, list[str]]]:
    failures: dict[str, list[str]] = {}

    def note(code: str, case_id: str) -> None:
        failures.setdefault(case_id, []).append(code)

    nonces: set[str] = set()
    sequences: set[int] = set()
    for item in submission.observations:
        proof = item.proof
        if proof is None:
            note("service_proof_missing", item.case_id)
        else:
            try:
                proof.verify(binding.proof_public_key if binding else "")
            except ProofError:
                note("service_proof_signature_invalid", item.case_id)
            if proof.kind != "response":
                note("service_proof_kind_invalid", item.case_id)
            if binding is not None and (
                proof.run_id,
                proof.approval_sha256,
                proof.config_sha256,
                proof.scope,
            ) != (
                binding.run_id,
                binding.approval_sha256,
                binding.config_sha256,
                binding.scope,
            ):
                note("service_proof_binding_mismatch", item.case_id)
            if proof.request_sha256 != canonical_digest(item.request):
                note("service_proof_request_mismatch", item.case_id)
            if proof.response_sha256 != item.response_sha256:
                note("service_proof_response_mismatch", item.case_id)
            if proof.http_status != item.http_status:
                note("service_proof_status_mismatch", item.case_id)
            if proof.nonce in nonces:
                note("service_proof_replayed", item.case_id)
            nonces.add(proof.nonce)
            if proof.sequence in sequences:
                note("service_proof_sequence_reused", item.case_id)
            sequences.add(proof.sequence)
        stamp = item.run_stamp
        if stamp is None:
            note("service_run_binding_missing", item.case_id)
        elif binding is not None and (
            stamp.run_id,
            stamp.approval_sha256,
            stamp.config_sha256,
            stamp.scope,
        ) != (
            binding.run_id,
            binding.approval_sha256,
            binding.config_sha256,
            binding.scope,
        ):
            note("service_run_binding_mismatch", item.case_id)
    by_code: dict[str, list[str]] = {}
    for case_id, codes in failures.items():
        for code in codes:
            by_code.setdefault(code, []).append(case_id)
    blockers = [
        {"code": code, "detail": f"{len(ids)} cases: {', '.join(ids[:5])}"}
        for code, ids in by_code.items()
    ]
    counts = {
        "verified": sum(item.case_id not in failures for item in submission.observations),
        "missing": len(by_code.get("service_proof_missing", [])),
    }
    return blockers, counts, failures


def _review_blockers(decisions: DecisionRecord | None, scores: list[CaseScore]) -> list[str]:
    """Every one of the 120 responses needs a review bound to that exact response."""
    blockers: list[str] = []
    if decisions is None:
        blockers.append("no recorded reviewer decisions")
    unreviewed = [item.case.id for item in scores if not item.reviewed]
    if unreviewed:
        blockers.append(f"{len(unreviewed)} of {len(scores)} responses have no valid review")
    return blockers


def score(
    labels: LabelSet,
    mapping: RuntimeMapping,
    submission: Submission,
    *,
    decisions: DecisionRecord | None,
    profile: str,
    dataset_paths: dict[str, str],
    binding: RunBinding | None = None,
    attestation: Attestation | None = None,
    narrative: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if profile not in {"disabled", "service"}:
        raise ValueError(f"unknown evaluation profile {profile!r}")
    by_case = {item.case_id: item for item in submission.observations}
    scores = [score_case(case, by_case.get(case.id), mapping, decisions) for case in labels.cases]
    duplicates = list(submission.duplicate_case_ids)
    missing_cases = [case.id for case in labels.cases if case.id not in by_case]
    unknown_cases = sorted(set(by_case) - {case.id for case in labels.cases})

    blockers = _label_blockers(labels)
    blockers.extend(
        _submission_blockers(
            submission,
            profile=profile,
            missing_cases=missing_cases,
            duplicates=duplicates,
            unknown_cases=unknown_cases,
        )
    )
    proof_counts = {"verified": 0, "missing": 0}
    if profile == "service":
        blockers.extend(_service_blockers(submission, binding=binding, attestation=attestation))
        proof_blockers, proof_counts, proof_failures = _service_proof_blockers(submission, binding)
        blockers.extend(proof_blockers)
        for item in scores:
            codes = proof_failures.get(item.case.id, [])
            if not codes:
                continue
            item.integrity = False
            item.failures.extend(
                AssertionFailure(code, "candidate evidence was not verified") for code in codes
            )
            for check, value in item.checks.items():
                if check != "reviewed" and value is not None:
                    item.checks[check] = False
    else:
        stamped = [item.case_id for item in submission.observations if item.proof is not None]
        if stamped:
            blockers.append(
                {
                    "code": "proof_under_disabled_profile",
                    "detail": f"{len(stamped)} responses carry a candidate proof under a "
                    "provider-free profile",
                }
            )

    answer_scores = [item for item in scores if item.case.disposition == "answer"]
    review_blockers = _review_blockers(decisions, scores)
    if review_blockers:
        blockers.append({"code": "answer_quality_unreviewed", "detail": "; ".join(review_blockers)})
    for code, attribute in (
        ("assertion_evidence_unresolved", "assertion_blockers"),
        ("citation_content_unverified", "citation_blockers"),
        ("entity_subject_unverifiable", "entity_blockers"),
    ):
        offenders = [item.case.id for item in scores if getattr(item, attribute)]
        if offenders:
            blockers.append(
                {
                    "code": code,
                    "detail": f"{len(offenders)} cases: {', '.join(offenders[:5])}",
                }
            )

    metrics: dict[str, dict[str, Any]] = {
        item.name: item.as_dict()
        for item in (
            *disposition_metrics(scores, review_blockers),
            *answer_metrics(answer_scores),
            *semantic_metrics(
                [item for item in scores if item.case.semantic_member],
                review_blockers,
            ),
            *review_metrics(answer_scores, decisions, review_blockers),
        )
    }
    metrics.update(latency_entries(submission))
    if narrative is not None:
        metrics.update(narrative["metrics"])
        blockers.extend(
            {"code": code, "detail": "separate document-level narrative benchmark"}
            for code in narrative["blockers"]
        )

    gates = _gates(metrics, blockers)
    for name, gate in gates.items():
        if gate["status"] == "fail":
            blockers.append({"code": f"gate_failed:{name}", "detail": "measured below threshold"})
        elif metrics[name]["status"] == "blocked":
            blockers.append(
                {"code": f"gate_blocked:{name}", "detail": "required measurement is unavailable"}
            )
    unmapped_labels = mapping.unmapped_references(
        [reference for case in labels.cases for reference in case.canonical_evidence_ids]
    )
    if unmapped_labels:
        blockers.append(
            {
                "code": "label_references_unmapped",
                "detail": f"{len(unmapped_labels)} canonical label references are not in the "
                "mapping",
            }
        )
    return {
        "schema": SCHEMA,
        "dataset": {
            **dataset_paths,
            "questions_sha256": labels.questions_sha256,
            "expectations_sha256": labels.expectations_sha256,
            "labels_sha256": labels.labels_sha256,
            "labels_digest_status": labels.labels_digest_status,
            "labels_digest_source": labels.labels_digest_source,
            "case_count": labels.case_count,
            "semantic_case_count": len(labels.semantic_cases),
            "dispositions_expected": labels.dispositions,
            "owner_approved": labels.owner_approved,
            "frozen": labels.frozen,
            "approval_recorded": labels.approval_recorded,
        },
        "mapping": {
            "version": mapping.version,
            "release_id": mapping.release_id,
            "scope": mapping.scope,
            "file_sha256": mapping.file_sha256,
            "rows": len(mapping.rows),
            "unmapped_canonical_references": len(unmapped_labels),
        },
        "profile": {
            "name": profile,
            "provider_requests": submission.provider_requests,
            "provider_attempts": None if attestation is None else attestation.admitted,
            "attempts_refused": None if attestation is None else attestation.refused,
            "attempt_budget": None if binding is None else binding.max_provider_requests,
            "spend_budget_nano_usd": (
                None if binding is None else binding.spend_bound.max_total_nano_usd
            ),
            "spend_upper_nano_usd": (
                None if attestation is None else attestation.upper_cost_nano_usd
            ),
            "spend_outstanding_nano_usd": (
                None if attestation is None else attestation.outstanding_nano_usd
            ),
            "run_id": None if binding is None else binding.run_id,
            "candidate": None if binding is None else binding.candidate,
            "scope": None if binding is None else binding.scope,
            "attested": None if attestation is None else attestation.ok,
            "proof_scope": None if binding is None else "service",
            "proofs_verified": proof_counts["verified"],
            "proofs_missing": proof_counts["missing"],
            "cases_observed": len(submission.observations),
            "cases_missing": missing_cases,
            "duplicates": duplicates,
            "unknown_cases": unknown_cases,
            "failures": [
                item["code"]
                for item in blockers
                if item["code"]
                in {
                    "cases_missing",
                    "duplicate_observation",
                    "unknown_case_observation",
                    "provider_requests_observed",
                    "run_stamp_under_disabled_profile",
                    "service_guard_unverified",
                    "service_guard_unattested",
                    "service_run_binding_missing",
                    "service_run_binding_mismatch",
                    "service_stages_absent",
                    "service_evidence_local_fake",
                    "service_proof_missing",
                    "service_proof_signature_invalid",
                    "service_proof_kind_invalid",
                    "service_proof_binding_mismatch",
                    "service_proof_request_mismatch",
                    "service_proof_response_mismatch",
                    "service_proof_status_mismatch",
                    "service_proof_replayed",
                    "service_proof_sequence_reused",
                    "proof_under_disabled_profile",
                }
            ],
        },
        "semantic": {
            "policy": "route_aware_behavior",
            "cases": len(labels.semantic_cases),
            "case_ids": list(labels.semantic_ids),
        },
        "narrative": narrative,
        "dispositions": {
            "expected": labels.dispositions,
            "observed": _observed(submission),
            "unverified": [
                item.case.id
                for item in scores
                if item.observation is not None and item.observation.outcome is None
            ],
        },
        "metrics": metrics,
        "gates": gates,
        "blockers": blockers,
        "release_blocked": bool(blockers),
        "cases": [item.as_dict() for item in scores],
    }
