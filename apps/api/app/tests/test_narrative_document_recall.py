"""Document recall must reject same-game substitutes and unbound observations.

Failure modes are game-level credit for a wrong chunk, stale payload/point identity,
emission-order drift, missing completion seals and duplicated observations.
These cases precede the narrative benchmark implementation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from app.evaluation.narrative_benchmark import Document, NarrativeBenchmark, NarrativeCase, digest
from app.evaluation.narrative_collection import SCHEMA
from app.evaluation.narrative_scoring import score_narrative
from app.services.release_bundle import canonical_json

VERSION = "2025-26.fixture"


def _benchmark():
    first = Document(
        "possession:0022500003:1",
        "game:1:poss:1",
        "knicks_possessions",
        "physical",
        "point-one",
        "1" * 64,
        1,
        "0022500003",
    )
    other = replace(
        first,
        canonical_id="possession:0022500003:2",
        document_id="game:1:poss:2",
        point_id="point-two",
        payload_sha256="2" * 64,
    )
    case = NarrativeCase(
        "narrative-fixture",
        "Describe the event.",
        "2025-26",
        "0022500003",
        1,
        "2025-10-22",
        "CLE",
        1,
        "11:20",
        frozenset({first.canonical_id}),
    )
    benchmark = NarrativeBenchmark(
        VERSION,
        (case,),
        {first.document_id: first, other.document_id: other},
        {"fixture": "independent-source"},
        {"settings": {"rag_fused_candidate_limit": 20}},
        (),
    )
    return benchmark, case, first, other


def _entry(document):
    return {
        "evidence_id": "vector:" + document.point_id,
        "document_id": document.document_id,
        "collection": "possessions",
        "point_id": document.point_id,
        "payload_sha256": document.payload_sha256,
        "game_id": document.game_id,
        "sequence_id": document.document_id,
        "score": 1.0,
        "rank": 1,
    }


def _rows(benchmark, case, document):
    run_id = "fixture-run"
    request = case.request(f"narrative-{run_id}-{case.id}")
    entry = _entry(document)
    output = {
        "status": "ok",
        "trace": {
            "kind": "retrieval_trace",
            "request_id": request["request_id"],
            "data_version": VERSION,
            "dense_status": "ok",
            "errors": [],
            "candidate_limit": 20,
            "candidate_limit_applied": True,
            "lexical_limit": 20,
            "dense_limit": 20,
            "lexical": [],
            "dense": [dict(entry)],
            "candidates": [dict(entry)],
            "selected": [dict(entry)],
        },
        "evidence": [
            {
                "evidence_id": VERSION + ":" + entry["evidence_id"],
                **{
                    key: entry[key]
                    for key in ("document_id", "point_id", "payload_sha256", "game_id")
                },
            }
        ],
    }
    header = {
        "kind": "manifest",
        "schema": SCHEMA,
        "run_id": run_id,
        "identity_sha256": benchmark.identity_sha256,
        "identity": benchmark.identity,
        "case_ids": [case.id],
        "paid_wording_requests": 0,
    }
    row = {
        "kind": "case",
        "schema": SCHEMA,
        "identity_sha256": benchmark.identity_sha256,
        "input": request,
        "input_sha256": digest(request),
        "output": output,
        "output_sha256": digest(output),
    }
    return header, row


def _score(tmp_path, benchmark, header, records, *, seal=True):
    for row in records:
        row["output_sha256"] = digest(row["output"])
    rows = [header, *records]
    if seal:
        rows.append(
            {
                "kind": "complete",
                "schema": SCHEMA,
                "run_id": header["run_id"],
                "identity_sha256": benchmark.identity_sha256,
                "records": len(records),
                "records_sha256": hashlib.sha256(
                    b"".join(canonical_json(row) + b"\n" for row in records)
                ).hexdigest(),
            }
        )
    path = tmp_path / "observations.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return score_narrative(benchmark, path, threshold=0.95)


def test_different_document_in_same_game_earns_no_recall(tmp_path):
    benchmark, case, _, other = _benchmark()
    header, row = _rows(benchmark, case, other)
    report = _score(tmp_path, benchmark, header, [row])
    assert report["metrics"]["narrative_recall_at_5"]["value"] == 0
    assert report["gate"]["status"] == "fail"
    assert report["cases_expected"] == 1


def test_correct_document_receives_recall_with_its_actual_emitted_identity(tmp_path):
    benchmark, case, target, _ = _benchmark()
    header, row = _rows(benchmark, case, target)
    report = _score(tmp_path, benchmark, header, [row])
    assert report["metrics"]["narrative_recall_at_5"]["value"] == 1
    assert report["gate"]["status"] == "pass"


@pytest.mark.parametrize("field,value", [("point_id", "foreign"), ("payload_sha256", "f" * 64)])
def test_stale_document_identity_never_gets_recall(tmp_path, field, value):
    benchmark, case, target, _ = _benchmark()
    header, row = _rows(benchmark, case, target)
    row["output"]["trace"]["selected"][0][field] = value
    report = _score(tmp_path, benchmark, header, [row])
    assert report["metrics"]["narrative_recall_at_5"]["numerator"] == 0
    assert report["release_blocked"] is True


def test_emitted_evidence_cannot_disagree_with_the_recorded_order(tmp_path):
    benchmark, case, target, other = _benchmark()
    header, row = _rows(benchmark, case, target)
    row["output"]["evidence"][0]["document_id"] = other.document_id
    report = _score(tmp_path, benchmark, header, [row])
    assert report["cases"][0]["valid"] is False
    assert report["metrics"]["narrative_recall_at_5"]["numerator"] == 0


def test_unsealed_or_duplicate_collection_never_shrinks_the_denominator(tmp_path):
    benchmark, case, target, _ = _benchmark()
    header, row = _rows(benchmark, case, target)
    for records, seal in (([row], False), ([row, row], True)):
        report = _score(tmp_path, benchmark, header, records, seal=seal)
        assert report["gate"]["status"] == "blocked"
        assert report["metrics"]["narrative_recall_at_5"]["denominator"] == 1
