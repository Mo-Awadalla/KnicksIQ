"""Strict document recall over correlated narrative retrieval observations."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app.evaluation.narrative_benchmark import (
    NarrativeBenchmark,
    NarrativeCase,
    NarrativeError,
    digest,
)
from app.evaluation.narrative_collection import SCHEMA
from app.services.release_bundle import canonical_json

STAGES = ("lexical", "dense", "candidates", "selected")


def _stage_ids(
    benchmark: NarrativeBenchmark,
    case: NarrativeCase,
    stage: Any,
) -> tuple[str, ...]:
    if not isinstance(stage, list):
        raise NarrativeError("trace_stage_missing")
    canonical: list[str] = []
    evidence_ids: set[str] = set()
    for rank, item in enumerate(stage, start=1):
        if not isinstance(item, dict):
            raise NarrativeError("trace_entry_malformed")
        if isinstance(item.get("rank"), bool) or item.get("rank") != rank:
            raise NarrativeError("trace_rank_invalid")
        sequence = item.get("sequence_id")
        if sequence is not None and not isinstance(sequence, str):
            raise NarrativeError("trace_sequence_id_not_opaque")
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise NarrativeError("trace_evidence_id_missing")
        if evidence_id in evidence_ids:
            raise NarrativeError("trace_duplicate_evidence")
        evidence_ids.add(evidence_id)
        score = item.get("score")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
        ):
            raise NarrativeError("trace_score_invalid")
        document = benchmark.resolve(item, case.game_id)
        canonical.append(document.canonical_id)
    if len(set(canonical)) != len(canonical):
        raise NarrativeError("trace_duplicate_document")
    return tuple(canonical)


def _case_result(
    benchmark: NarrativeBenchmark,
    case: NarrativeCase,
    record: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "case_id": case.id,
        "relevant_document_ids": sorted(case.relevant_ids),
        "valid": False,
        "hybrid": False,
        "problems": [],
        "stages": {},
    }
    try:
        request_id = f"narrative-{run_id}-{case.id}"
        expected_input = case.request(request_id)
        if (
            record.get("schema") != SCHEMA
            or record.get("identity_sha256") != benchmark.identity_sha256
            or record.get("input") != expected_input
            or record.get("input_sha256") != digest(expected_input)
        ):
            raise NarrativeError("narrative_input_identity_mismatch")
        output = record.get("output")
        if not isinstance(output, dict):
            raise NarrativeError("narrative_output_missing")
        if record.get("output_sha256") != digest(output):
            raise NarrativeError("narrative_output_hash_mismatch")
        trace = output.get("trace")
        if not isinstance(trace, dict):
            raise NarrativeError("narrative_trace_missing")
        if (
            trace.get("request_id") != request_id
            or trace.get("data_version") != benchmark.version
            or trace.get("kind") != "retrieval_trace"
        ):
            raise NarrativeError("narrative_trace_correlation_mismatch")
        if trace.get("dense_status") != "ok":
            raise NarrativeError("narrative_hybrid_not_completed")
        if trace.get("errors"):
            raise NarrativeError("narrative_trace_contains_errors")
        if output.get("status") not in {"ok", "no_matching_results"}:
            raise NarrativeError("narrative_tool_failed")
        if (
            trace.get("candidate_limit")
            != benchmark.profile["settings"]["rag_fused_candidate_limit"]
            or trace.get("candidate_limit_applied") is not True
            or trace.get("lexical_limit") != 20
            or trace.get("dense_limit") != 20
        ):
            raise NarrativeError("narrative_trace_limits_mismatch")

        stages = {name: _stage_ids(benchmark, case, trace.get(name)) for name in STAGES}
        if not set(stages["selected"]) <= set(stages["candidates"]):
            raise NarrativeError("selected_document_not_in_fused_candidates")
        emitted = output.get("evidence")
        if not isinstance(emitted, list):
            raise NarrativeError("emitted_evidence_missing")
        selected_entries = trace["selected"]
        if len(emitted) != len(selected_entries):
            raise NarrativeError("post_filter_trace_length_mismatch")
        for selected, evidence in zip(selected_entries, emitted, strict=True):
            if not isinstance(evidence, dict):
                raise NarrativeError("emitted_evidence_malformed")
            if evidence.get("evidence_id") != (f"{benchmark.version}:{selected['evidence_id']}"):
                raise NarrativeError("post_filter_trace_order_mismatch")
            for key in (
                "document_id",
                "point_id",
                "payload_sha256",
                "game_id",
            ):
                if evidence.get(key) != selected.get(key):
                    raise NarrativeError("post_filter_trace_identity_mismatch")

        result["valid"] = True
        result["hybrid"] = True
        for name, ids in stages.items():
            result["stages"][name] = {
                "document_ids": list(ids),
                "recall_at_5": (len(case.relevant_ids & set(ids[:5])) / len(case.relevant_ids)),
                "recall_at_20": (len(case.relevant_ids & set(ids[:20])) / len(case.relevant_ids)),
            }
    except (NarrativeError, KeyError, TypeError, ValueError) as exc:
        result["problems"].append(str(exc))
    return result


def score_narrative(
    benchmark: NarrativeBenchmark,
    observations_path: Path,
    *,
    threshold: float,
) -> dict[str, Any]:
    raw = observations_path.read_bytes()
    blockers: list[str] = list(benchmark.approval_problems)
    rows: list[dict[str, Any]] = []
    malformed = False
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("observation row is not an object")
            rows.append(row)
        except (ValueError, TypeError):
            malformed = True
    if malformed or len(rows) < 2:
        blockers.append("narrative_observations_malformed")
    header = rows[0] if rows else {}
    footer = rows[-1] if rows else {}
    run_id = header.get("run_id")
    expected_ids = [case.id for case in benchmark.cases]
    if (
        header.get("kind") != "manifest"
        or header.get("schema") != SCHEMA
        or not isinstance(run_id, str)
        or not run_id
        or header.get("identity_sha256") != benchmark.identity_sha256
        or header.get("identity") != benchmark.identity
        or header.get("case_ids") != expected_ids
        or header.get("paid_wording_requests") != 0
    ):
        blockers.append("narrative_manifest_mismatch")
        run_id = ""

    records: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    unknown: list[str] = []
    rolling = hashlib.sha256()
    for row in rows[1:-1]:
        if row.get("kind") != "case":
            blockers.append("narrative_unexpected_observation_kind")
            continue
        rolling.update(canonical_json(row) + b"\n")
        request = row.get("input")
        case_id = request.get("case_id") if isinstance(request, dict) else None
        if case_id not in expected_ids:
            unknown.append(str(case_id))
        elif case_id in records:
            duplicates.append(case_id)
        else:
            records[case_id] = row
    missing = [case_id for case_id in expected_ids if case_id not in records]
    if duplicates:
        blockers.append("narrative_duplicate_cases")
    if unknown:
        blockers.append("narrative_unknown_cases")
    if missing:
        blockers.append("narrative_missing_cases")
    if (
        footer.get("kind") != "complete"
        or footer.get("schema") != SCHEMA
        or footer.get("run_id") != run_id
        or footer.get("identity_sha256") != benchmark.identity_sha256
        or footer.get("records") != len(rows[1:-1])
        or footer.get("records_sha256") != rolling.hexdigest()
    ):
        blockers.append("narrative_collection_unsealed")

    scores = []
    for case in benchmark.cases:
        record = records.get(case.id)
        if record is None:
            scores.append(
                {
                    "case_id": case.id,
                    "valid": False,
                    "hybrid": False,
                    "problems": ["narrative_missing_case"],
                    "stages": {},
                }
            )
        else:
            scores.append(_case_result(benchmark, case, record, run_id))
    invalid = [row["case_id"] for row in scores if not row["valid"]]
    if invalid:
        blockers.append("narrative_case_integrity_failed")

    structural = any(
        code
        in {
            "narrative_observations_malformed",
            "narrative_manifest_mismatch",
            "narrative_unexpected_observation_kind",
            "narrative_duplicate_cases",
            "narrative_unknown_cases",
            "narrative_missing_cases",
            "narrative_collection_unsealed",
        }
        for code in blockers
    )
    denominator = len(benchmark.cases)
    metrics: dict[str, Any] = {}
    for stage in STAGES:
        for cutoff in (5, 20):
            numerator = sum(
                row["stages"].get(stage, {}).get(f"recall_at_{cutoff}", 0.0)
                for row in scores
                if row["valid"]
            )
            name = (
                f"narrative_recall_at_{cutoff}"
                if stage == "selected"
                else f"narrative_{stage}_recall_at_{cutoff}"
            )
            metrics[name] = {
                "status": "blocked" if structural else "measured",
                "numerator": numerator,
                "denominator": denominator,
                "value": None if structural else numerator / denominator,
                "blockers": sorted(set(blockers)) if structural else [],
                "failing_cases": [
                    row["case_id"]
                    for row in scores
                    if not row["valid"]
                    or row["stages"].get(stage, {}).get(f"recall_at_{cutoff}", 0.0) < 1.0
                ],
            }

    gate_metric = metrics["narrative_recall_at_5"]
    gate = {
        "threshold": threshold,
        "value": gate_metric["value"],
        "status": (
            "blocked"
            if blockers
            else (
                "pass"
                if gate_metric["value"] is not None and gate_metric["value"] >= threshold
                else "fail"
            )
        ),
        "blocked_by": sorted(set(blockers)),
    }
    return {
        "schema": "narrative-retrieval-report-v1",
        "identity": benchmark.identity,
        "identity_sha256": benchmark.identity_sha256,
        "observations_sha256": hashlib.sha256(raw).hexdigest(),
        "cases_expected": denominator,
        "cases_observed": len(records),
        "missing": missing,
        "duplicates": duplicates,
        "unknown": unknown,
        "paid_wording_requests": 0,
        "measurement": "real archive-tool hybrid document retrieval",
        "not_measured": "twenty end-to-end model narrative answers",
        "metrics": metrics,
        "gate": gate,
        "blockers": sorted(set(blockers)),
        "release_blocked": bool(blockers) or gate["status"] != "pass",
        "cases": scores,
    }
