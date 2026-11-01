"""Label loading, request-correlated collection and fail-closed scoring.

Subcommands:
  labels   load the immutable labels + local mapping and print their blocking state
  collect  send every case as its own turn and record exact responses
  score    score recorded responses against the frozen expectations

No subcommand calls a model provider itself. The ``disabled`` profile is
loopback-only and provider-free. The ``service`` profile collects under an
approved run configuration, proves the candidate's durable claim and then its
live signature over a challenge before the first analyst POST, accepts a
response only with the candidate's own proof, stamps every response with the run
identity, and scores only against a sealed, attested ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from app.evaluation import narrative_cli, runner
from app.evaluation.attempt_ledger import Attestation, LedgerError, attest
from app.evaluation.collection_transport import RunnerError
from app.evaluation.labels import (
    LabelError,
    LabelSet,
    evaluation_identity,
    identity_digest,
    load_labels,
)
from app.evaluation.mapping import MappingError, RuntimeMapping, load_documents, load_mapping
from app.evaluation.narrative_benchmark import NarrativeError
from app.evaluation.observations import ObservationError, load_responses
from app.evaluation.provider_approval import ApprovalError
from app.evaluation.provider_guard import RunBinding
from app.evaluation.reviews import ReviewError, load_decisions
from app.evaluation.scoring import score


def _load_labels(args: argparse.Namespace) -> LabelSet:
    return load_labels(Path(args.questions), Path(args.expectations))


def _load_mapping(args: argparse.Namespace) -> tuple[RuntimeMapping, str | None]:
    mapping = load_mapping(Path(args.mapping))
    documents = getattr(args, "documents", None)
    if not documents:
        return mapping, None
    path = Path(documents)
    return load_documents(path, mapping), hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(
    args: argparse.Namespace,
    labels: LabelSet,
    mapping: RuntimeMapping,
    documents_sha256: str | None,
) -> dict:
    return evaluation_identity(
        labels,
        mapping_sha256=mapping.file_sha256,
        documents_sha256=documents_sha256,
        narrative_sha256=narrative_cli.labels_digest(args),
    )


def _write(path: Path | None, payload: dict) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered)


def _labels_report(labels: LabelSet, mapping: RuntimeMapping, identity: dict) -> dict:
    blockers: list[dict[str, str]] = []
    if labels.owner_approved < labels.case_count:
        blockers.append(
            {
                "code": "labels_owner_unapproved",
                "detail": f"{labels.case_count - labels.owner_approved} of "
                f"{labels.case_count} cases have no owner approval",
            }
        )
    if not labels.frozen:
        blockers.append(
            {
                "code": "labels_not_frozen",
                "detail": "; ".join(labels.freeze_problems) or "no freeze manifest",
            }
        )
    if labels.approval_problems:
        blockers.append(
            {
                "code": "labels_approval_unverified",
                "detail": "; ".join(labels.approval_problems),
            }
        )
    if labels.labels_digest_status != "verified":
        blockers.append(
            {
                "code": "labels_digest_unverified",
                "detail": "recorded labels_sha256 matches no available artifact",
            }
        )
    semantic = labels.semantic_cases
    references = [reference for case in labels.cases for reference in case.canonical_evidence_ids]
    unmapped = mapping.unmapped_references(references)
    return {
        "schema": "evaluation-labels-v1",
        "dataset": {
            "questions_sha256": labels.questions_sha256,
            "expectations_sha256": labels.expectations_sha256,
            "labels_sha256": labels.labels_sha256,
            "labels_digest_status": labels.labels_digest_status,
            "labels_digest_source": labels.labels_digest_source,
            "case_count": labels.case_count,
            "semantic_case_count": len(semantic),
            "dispositions_expected": labels.dispositions,
            "owner_approved": labels.owner_approved,
            "frozen": labels.frozen,
            "approval_recorded": labels.approval_recorded,
            "freeze_sha256": labels.freeze_sha256,
            "freeze_problems": list(labels.freeze_problems),
            "approval_problems": list(labels.approval_problems),
            "semantic_case_ids": list(labels.semantic_ids),
            "identity_sha256": identity_digest(identity),
            "narrative_labels_sha256": identity["narrative_labels_sha256"],
        },
        "mapping": {
            "version": mapping.version,
            "release_id": mapping.release_id,
            "scope": mapping.scope,
            "file_sha256": mapping.file_sha256,
            "rows": len(mapping.rows),
            "canonical_references": len(references),
            "unique_canonical_references": len(set(references)),
            "unmapped_canonical_references": len(unmapped),
        },
        "semantic": {
            "cases": len(semantic),
            "policy": "route_aware_behavior",
            "case_ids": list(labels.semantic_ids),
        },
        "blockers": blockers,
        "release_blocked": bool(blockers),
    }


def _command_labels(args: argparse.Namespace) -> int:
    labels = _load_labels(args)
    mapping, documents_sha256 = _load_mapping(args)
    identity = _identity(args, labels, mapping, documents_sha256)
    _write(Path(args.output) if args.output else None, _labels_report(labels, mapping, identity))
    return 0


def _command_narrative(args: argparse.Namespace) -> int:
    labels = _load_labels(args)
    mapping, documents_sha256 = _load_mapping(args)
    identity = _identity(args, labels, mapping, documents_sha256)
    report = narrative_cli.evaluate(
        args, primary_identity_sha256=identity_digest(identity), collect=args.collect
    )
    if report is None:
        raise NarrativeError("Narrative scoring requires its source-labelled benchmark")
    _write(Path(args.output) if args.output else None, report)
    return 0


def _command_collect(args: argparse.Namespace) -> int:
    labels = _load_labels(args)
    records, summary = runner.collect(
        list(labels.cases),
        base_url=args.base_url,
        profile=args.profile,
        timeout=args.timeout,
        season=args.season,
        limit=args.limit,
        labels_sha256=labels.labels_sha256,
        run_config=Path(args.run_config) if args.run_config else None,
        run_config_sha256=args.run_config_sha256 or "",
    )
    target = Path(args.responses)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in records
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "profile": summary.profile,
                "cases_requested": summary.cases_requested,
                "cases_recorded": summary.cases_recorded,
                "http_errors": summary.http_errors,
                "provider_stages": summary.provider_stages,
                "provider_attempts": summary.provider_attempts,
                "attempts_refused": summary.attempts_refused,
                "proofs_verified": summary.proofs_verified,
                "run_id": summary.run_id,
                "scope": summary.scope,
                "base_url": summary.base_url,
                "responses": str(target),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _service_proof(args: argparse.Namespace) -> tuple[RunBinding, Attestation]:
    """Load the issued run configuration and attest its sealed attempt ledger."""
    if not getattr(args, "run_config", None):
        raise RunnerError(
            "the service profile needs --run-config: the run configuration issued for the "
            "operator's approval"
        )
    if not (args.run_config_sha256 or "").strip():
        raise RunnerError(
            "the service profile needs --run-config-sha256, the digest announced with the "
            "run configuration"
        )
    binding = RunBinding.load(Path(args.run_config), expected_sha256=args.run_config_sha256.strip())
    attestation = attest(binding.ledger(), require_sealed=True)
    return binding, attestation


def _command_score(args: argparse.Namespace) -> int:
    labels = _load_labels(args)
    mapping, documents_sha256 = _load_mapping(args)
    identity = _identity(args, labels, mapping, documents_sha256)
    submission = load_responses(Path(args.responses))
    decisions = None
    if args.reviews:
        decisions = load_decisions(
            Path(args.reviews),
            identity_sha256=identity_digest(identity),
            questions_sha256=labels.questions_sha256,
            cases={case.id: (len(case.facts), case.disposition) for case in labels.cases},
        )
    binding = attestation = None
    if args.profile == "service":
        binding, attestation = _service_proof(args)
        loaded_identity = identity_digest(identity)
        if binding.identity_sha256 != loaded_identity:
            raise RunnerError(
                "the run configuration binds evaluation identity "
                f"{binding.identity_sha256}, not the loaded identity {loaded_identity}"
            )
    narrative = narrative_cli.evaluate(args, primary_identity_sha256=identity_digest(identity))
    report = score(
        labels,
        mapping,
        submission,
        decisions=decisions,
        profile=args.profile,
        dataset_paths={
            "questions": str(Path(args.questions)),
            "expectations": str(Path(args.expectations)),
            "mapping": str(Path(args.mapping)),
            "responses": str(Path(args.responses)),
            "narrative_labels_sha256": identity["narrative_labels_sha256"],
            "identity_sha256": identity_digest(identity),
        },
        binding=binding,
        attestation=attestation,
        narrative=narrative,
    )
    _write(Path(args.output) if args.output else None, report)
    if args.profile == "disabled" and submission.provider_requests:
        print(
            f"{submission.provider_requests} model stages were reported under the disabled "
            "profile; this run cannot claim zero provider requests",
            file=sys.stderr,
        )
        return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    labels = sub.add_parser("labels", help="load and validate labels without running anything")
    for name in ("questions", "expectations", "mapping"):
        labels.add_argument(f"--{name}", required=True)
    labels.add_argument(
        "--documents",
        help="optional local index document identity mapping for narrative receipts",
    )
    labels.add_argument("--output")
    narrative_cli.add_arguments(labels)
    labels.set_defaults(handler=_command_labels)

    collect = sub.add_parser("collect", help="record one request-correlated response per case")
    collect.add_argument("--questions", required=True)
    collect.add_argument("--expectations", required=True)
    collect.add_argument("--base-url", default="http://127.0.0.1:8000")
    collect.add_argument("--profile", choices=("disabled", "service"), default="disabled")
    collect.add_argument("--season", default="2025-26")
    collect.add_argument("--timeout", type=float, default=40.0)
    collect.add_argument("--limit", type=int)
    collect.add_argument(
        "--run-config",
        help="service profile only: the run configuration issued for the operator's approval",
    )
    collect.add_argument(
        "--run-config-sha256",
        help="service profile only: the digest announced with that run configuration",
    )
    collect.add_argument("--responses", required=True)
    collect.set_defaults(handler=_command_collect)

    narrative = sub.add_parser("narrative", help="collect or score real hybrid document retrieval")
    for name in ("questions", "expectations", "mapping", "documents"):
        narrative.add_argument(f"--{name}", required=True)
    narrative_cli.add_arguments(narrative)
    narrative.add_argument("--collect", action="store_true")
    narrative.add_argument("--output")
    narrative.set_defaults(handler=_command_narrative)

    score_parser = sub.add_parser("score", help="score recorded responses against expectations")
    for name in ("questions", "expectations", "mapping", "responses"):
        score_parser.add_argument(f"--{name}", required=True)
    score_parser.add_argument(
        "--documents",
        help="optional local index document identity mapping for narrative receipts",
    )
    score_parser.add_argument("--reviews")
    score_parser.add_argument("--profile", choices=("disabled", "service"), default="disabled")
    score_parser.add_argument(
        "--run-config",
        help="service profile only: the run configuration issued for the operator's approval",
    )
    score_parser.add_argument(
        "--run-config-sha256",
        help="service profile only: the digest announced with that run configuration",
    )
    score_parser.add_argument("--output")
    narrative_cli.add_arguments(score_parser)
    score_parser.set_defaults(handler=_command_score)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        LabelError,
        MappingError,
        ObservationError,
        ReviewError,
        ApprovalError,
        LedgerError,
        RunnerError,
        NarrativeError,
    ) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
