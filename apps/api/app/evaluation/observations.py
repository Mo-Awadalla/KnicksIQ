"""Typed runtime observations: what one request actually returned, and its trace.

The response is read as data. Nothing here infers an answer's disposition from
prose: ``outcome`` must be present, and a missing outcome is an observation
failure rather than an abstention.

A record also carries the request it was sent with (question, season, context,
turn, expected revision and the sent request id). A response is only credited to
a case when that identity is present and consistent, so a self-consistent
response cannot be reassigned to another question.

``response["evidence"]``, when the candidate emits it, is the backend-generated
evidence registry for that turn: the receipts and calculation expansions the
answer was built from. It is read as an authoritative snapshot for this response
only; nothing here treats a stored row as proof of a persistent commit. The
registry and the retrieval traces are read as records in ``observations_records``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.evaluation.candidate_proof import ProofError, ResponseProof
from app.evaluation.observations_records import (
    EvidenceRecord,
    ObservationError,
    TraceEntry,
    evidence_registry,
)
from app.evaluation.run_stamp import RunStamp, RunStampError, record_binding

PROVIDER_STAGES = frozenset({"orchestrate", "revise", "review"})
FactValue = int | float | dict[str, Any] | str
_RESPONSE_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def canonical_digest(value: Any) -> str:
    import hashlib

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class TypedClaim:
    claim_id: str
    subject_id: str | None
    metric_id: str
    value: FactValue
    unit: str | None
    population: str
    filters: dict[str, Any]
    season: str
    season_type: str | None
    game_ids: tuple[int, ...]
    window: dict[str, Any] | None
    sample_size: int | None
    denominator: float | None
    release_id: str
    supporting_evidence_ids: tuple[str, ...]
    statement: str
    eligibility: dict[str, Any] = field(default_factory=dict)
    baseline_claim_ids: tuple[str, ...] = ()

    @property
    def metric_tokens(self) -> frozenset[str]:
        return frozenset(
            token for token in re.split(r"[^a-z0-9]+", self.metric_id.casefold()) if token
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TypedClaim:
        required = (
            "claim_id",
            "metric_id",
            "value",
            "population",
            "season",
            "release_id",
            "supporting_evidence_ids",
            "statement",
        )
        missing = [name for name in required if name not in value]
        if missing:
            raise ObservationError(f"claim is missing {', '.join(missing)}")
        raw_value = value["value"]
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, dict, str)):
            raise ObservationError("claim value has unsupported type")
        game_ids = value.get("game_ids") or []
        if any(isinstance(item, bool) or not isinstance(item, int) for item in game_ids):
            raise ObservationError("claim game_ids must be integers")
        denominator = value.get("denominator")
        if denominator is not None and (
            isinstance(denominator, bool) or not isinstance(denominator, (int, float))
        ):
            raise ObservationError("claim denominator must be numeric")
        window = value.get("window")
        if window is not None and not isinstance(window, dict):
            raise ObservationError("claim window is not an object")
        eligibility = value.get("eligibility") or {}
        if not isinstance(eligibility, dict):
            raise ObservationError("claim eligibility is not an object")
        baseline = value.get("baseline_claim_ids") or []
        if not isinstance(baseline, list):
            raise ObservationError("claim baseline_claim_ids is not a list")
        return cls(
            claim_id=str(value["claim_id"]),
            subject_id=value.get("subject_id"),
            metric_id=str(value["metric_id"]),
            value=raw_value,
            unit=value.get("unit"),
            population=str(value["population"]),
            filters=dict(value.get("filters") or {}),
            season=str(value["season"]),
            season_type=value.get("season_type"),
            game_ids=tuple(int(item) for item in game_ids),
            window=window,
            sample_size=value.get("sample_size"),
            denominator=None if denominator is None else float(denominator),
            release_id=str(value["release_id"]),
            supporting_evidence_ids=tuple(
                str(item) for item in value.get("supporting_evidence_ids") or []
            ),
            statement=str(value["statement"]),
            eligibility=dict(eligibility),
            baseline_claim_ids=tuple(str(item) for item in baseline),
        )


@dataclass(frozen=True)
class Citation:
    claim_text: str
    type: str
    game_id: int | None
    evidence_id: str
    claim: TypedClaim | None
    possession_id: str | None = None


@dataclass(frozen=True)
class Observation:
    case_id: str
    turn_id: str
    request_id: str
    outcome: str | None
    answer: str
    claims: tuple[TypedClaim, ...]
    citations: tuple[Citation, ...]
    analytics_status: str | None
    analytics_result_count: int
    traces: tuple[TraceEntry, ...]
    degraded: bool
    refused: bool
    route: str | None
    llm_validated: bool
    latency_ms: float
    http_status: int
    response_sha256: str
    model_stages: int = 0
    problems: tuple[str, ...] = ()
    request: dict[str, Any] = field(default_factory=dict)
    sent_request_id: str = ""
    evidence: dict[str, EvidenceRecord] = field(default_factory=dict)
    run_stamp: RunStamp | None = None
    proof: ResponseProof | None = None


def _claims_from(response: dict[str, Any]) -> tuple[tuple[TypedClaim, ...], tuple[str, ...]]:
    claims: dict[str, TypedClaim] = {}
    problems: list[str] = []
    for citation in response.get("citations") or []:
        metadata = citation.get("metadata") if isinstance(citation, dict) else None
        raw = (metadata or {}).get("claim")
        if not isinstance(raw, dict):
            continue
        try:
            claim = TypedClaim.from_dict(raw)
        except ObservationError as exc:
            problems.append(f"malformed_claim:{exc}")
            continue
        claims.setdefault(claim.claim_id, claim)
    return tuple(claims.values()), tuple(problems)


def _citations(response: dict[str, Any]) -> tuple[Citation, ...]:
    parsed: list[Citation] = []
    for citation in response.get("citations") or []:
        if not isinstance(citation, dict):
            continue
        metadata = citation.get("metadata") or {}
        raw_claim = metadata.get("claim")
        claim = None
        if isinstance(raw_claim, dict):
            try:
                claim = TypedClaim.from_dict(raw_claim)
            except ObservationError:
                claim = None
        parsed.append(
            Citation(
                claim_text=str(citation.get("claim") or ""),
                type=str(citation.get("type") or ""),
                game_id=citation.get("game_id"),
                evidence_id=str(metadata.get("evidence_id") or ""),
                claim=claim,
                possession_id=(
                    str(metadata["possession_id"]) if metadata.get("possession_id") else None
                ),
            )
        )
    return tuple(parsed)


def parse_record(record: dict[str, Any]) -> Observation:
    try:
        case_id = str(record["case_id"])
        response = record["response"]
    except KeyError as exc:
        raise ObservationError(f"record is missing {exc.args[0]}") from exc
    if not isinstance(response, dict):
        raise ObservationError("response is not an object")
    try:
        binding = record_binding(record)
    except (RunStampError, ProofError) as exc:
        raise ObservationError(str(exc)) from exc
    problems: list[str] = []
    recorded_digest = str(record.get("response_sha256") or "")
    if not _RESPONSE_DIGEST.match(recorded_digest):
        problems.append("response_hash_missing")
    elif recorded_digest != canonical_digest(response):
        problems.append("response_hash_mismatch")
    claims, claim_problems = _claims_from(response)
    problems.extend(claim_problems)
    evidence, registry_problems = evidence_registry(response)
    problems.extend(registry_problems)

    request = record.get("request")
    if not isinstance(request, dict) or not request:
        problems.append("request_identity_missing")
        request = {}
    else:
        if not str(request.get("question") or "").strip():
            problems.append("request_question_missing")
        if not str(request.get("season") or "").strip():
            problems.append("request_season_missing")
        if not str(request.get("turn_id") or "").strip():
            problems.append("request_turn_missing")
        if not isinstance(request.get("expected_revision"), int):
            problems.append("request_revision_missing")
    recorded_turn = str(record.get("turn_id") or "")
    if not recorded_turn:
        problems.append("turn_identity_missing")
    elif request and recorded_turn != str(request.get("turn_id") or ""):
        problems.append("turn_identity_mismatch")
    sent_request_id = str(record.get("request_id") or "")
    if not sent_request_id:
        problems.append("request_id_missing")
    elif str(response.get("request_id") or "") != sent_request_id:
        problems.append("response_request_id_mismatch")
    traces: list[TraceEntry] = []
    for entry in response.get("tool_calls") or []:
        if not isinstance(entry, dict) or entry.get("kind") != "retrieval_trace":
            continue
        try:
            traces.append(TraceEntry.from_dict(entry))
        except (ObservationError, KeyError, TypeError, ValueError) as exc:
            problems.append(f"malformed_trace:{type(exc).__name__}")
    analytics = response.get("analytics") or {}
    model_stages = sum(
        1
        for entry in response.get("tool_calls") or []
        if isinstance(entry, dict)
        and (entry.get("stage") in PROVIDER_STAGES or str(entry.get("tool", "")).startswith("llm_"))
    )
    outcome = response.get("outcome")
    if outcome not in (None, "answer", "clarify", "refuse"):
        problems.append("outcome_invalid")
        outcome = None
    return Observation(
        case_id=case_id,
        turn_id=str(record.get("turn_id") or ""),
        request_id=str(response.get("request_id") or ""),
        outcome=outcome,
        answer=str(response.get("answer") or ""),
        claims=claims,
        citations=_citations(response),
        analytics_status=analytics.get("status") if isinstance(analytics, dict) else None,
        analytics_result_count=(
            len(analytics.get("results") or []) if isinstance(analytics, dict) else 0
        ),
        traces=tuple(traces),
        degraded=bool(response.get("degraded")),
        refused=bool(response.get("refused")),
        route=response.get("route"),
        llm_validated=bool(response.get("llm_validated")),
        latency_ms=float(record.get("latency_ms") or 0),
        http_status=int(record.get("http_status") or 0),
        response_sha256=canonical_digest(response),
        model_stages=model_stages,
        problems=tuple(problems),
        request=request,
        sent_request_id=sent_request_id,
        evidence=evidence,
        run_stamp=binding.stamp,
        proof=binding.proof,
    )


@dataclass(frozen=True)
class Submission:
    observations: tuple[Observation, ...]
    duplicate_case_ids: tuple[str, ...]
    run: RunStamp | None = None

    @property
    def provider_requests(self) -> int:
        """Model stages the responses themselves report; retrieval stages never count."""
        return sum(item.model_stages for item in self.observations)


def load_responses(path: Path) -> Submission:
    observations: list[Observation] = []
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    stamps: set[RunStamp] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        observation = parse_record(record)
        try:
            binding = record_binding(record)
        except (RunStampError, ProofError) as exc:
            raise ObservationError(str(exc)) from exc
        if binding.stamp is not None:
            stamps.add(binding.stamp)
        seen[observation.case_id] = seen.get(observation.case_id, 0) + 1
        if seen[observation.case_id] > 1:
            duplicates.append(observation.case_id)
        observations.append(observation)
    if len(stamps) > 1:
        raise ObservationError(
            f"responses carry {len(stamps)} different run identities; one submission is one run"
        )
    return Submission(
        tuple(observations),
        tuple(dict.fromkeys(duplicates)),
        next(iter(stamps)) if stamps else None,
    )
