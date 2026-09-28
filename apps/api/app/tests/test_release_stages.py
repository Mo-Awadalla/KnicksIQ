"""Fail-closed stage and deployment authorization contracts (tests first).

Failure matrix: configuration-only shadow; absent/altered/wrong-candidate evidence;
missing/duplicate turns; chosen sample instead of fixed IDs; unsampled calls;
selected fallback counted as model success; primary delivery in shadow; altered
expectations; missing owner labels; readiness requiring premature launch approval;
missing/mismatched final record digest; legacy single-stage record accepted.
"""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from app.services import release_evidence as gate


def artifact(root, name, payload):
    path = root / (name + ".json")
    path.write_text(json.dumps(payload, sort_keys=True))
    return {"path": path.name, "sha256": gate.sha256(path)}


def ready_record(root):
    commit, bundle, expectations = "a" * 40, "b" * 64, "c" * 64
    record = {
        "id": "synthetic",
        "tested_commit": commit,
        "pre_promotion_configuration": {
            "answer_mode": "shadow",
            "shadow_sample_rate": 0.1,
            "analyst_evidence_loop_enabled": True,
        },
        "launch_configuration": {
            "answer_mode": "llm_primary",
            "analyst_evidence_loop_enabled": True,
        },
        "hashes": {"data": "d" * 64, "bundle": bundle, "evaluation": expectations},
        "checks": {},
        "approvals": {},
        "rollback": {
            "api_deployment": "api",
            "web_deployment": "web",
            "data_version": "old",
            "qdrant_aliases": {"games": "old"},
        },
    }
    for name in gate.REQUIRED_CHECKS:
        payload = {
            "tested_commit": commit,
            "bundle_sha256": bundle,
            "expectations_sha256": expectations,
        }
        record["checks"][name] = {
            "status": "passed",
            "tested_commit": commit,
            **artifact(root, name, payload),
        }
    for mode in ["evaluation", "evaluation_services_disabled"]:
        record["checks"][mode]["metrics"] = {
            **dict.fromkeys(gate.MINIMUMS, 1.0),
            "query_count": 120,
            "missing_labels": 0,
            "missing_ranked_traces": 0,
            "semantic_case_count": 50,
        }
    record["checks"]["warm_load"]["metrics"] = {
        "concurrency": 10,
        "archive_p95_ms": 10,
        "analyst_p95_ms": 20,
        "error_rate": 0,
    }
    record["checks"]["accessibility"]["metrics"] = {"serious": 0, "critical": 0}
    for name in ["template", "exceptions", "report_audit", "evaluation_labels"]:
        record["approvals"][name] = {
            "owner": "synthetic owner",
            "approved_at": "2026-01-01",
            **artifact(root, name + "-approval", {}),
        }
    ids = [
        json.loads(line)["id"]
        for line in (Path(gate.__file__).parents[1] / "evaluation/questions.jsonl")
        .read_text()
        .splitlines()
    ]
    turns = []
    for case_id in ids:
        request_id = hashlib.sha256(f"{expectations}:shadow:{case_id}".encode()).hexdigest()
        sampled = (
            int.from_bytes(hashlib.sha256(request_id.encode()).digest()[:4], "big") / (2**32 - 1)
            < 0.1
        )
        turns.append(
            {
                "case_id": case_id,
                "request_id": request_id,
                "sampled": sampled,
                "model_calls": 2 if sampled else 0,
                "model_validated": sampled,
                "delivered_mode": "factual_fallback",
                "state_committed": True,
                "replayed": False,
                "error": None,
            }
        )
    payload = {
        "tested_commit": commit,
        "bundle_sha256": bundle,
        "expectations_sha256": expectations,
        "configuration": record["pre_promotion_configuration"],
        "case_ids": ids,
        "turns": turns,
        "scope": "isolated_staging",
        "passed": True,
    }
    record["checks"]["shadow_evaluation"] = {
        "status": "passed",
        "tested_commit": commit,
        **artifact(root, "shadow_evaluation", payload),
    }
    return record, payload


def test_readiness_precedes_launch_approval(tmp_path):
    record, _ = ready_record(tmp_path)
    assert gate.validate_readiness(record, tmp_path) == []
    assert any("launch" in f for f in gate.validate_record(record, tmp_path))
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record))
    assert gate.validate_deployment_authorization(record, tmp_path, path, None)
    assert gate.validate_deployment_authorization(record, tmp_path, path, "e" * 64)


@pytest.mark.parametrize(
    "defect",
    [
        "unsampled_call",
        "selected_fallback",
        "missing_turn",
        "wrong_commit",
        "wrong_bundle",
        "primary_delivery",
        "chosen_request_id",
        "duplicate_turn",
        "boolean_only",
    ],
)
def test_invalid_shadow_evidence_blocks_readiness(tmp_path, defect):
    record, payload = ready_record(tmp_path)
    selected = next(t for t in payload["turns"] if t["sampled"])
    unsampled = next(t for t in payload["turns"] if not t["sampled"])
    if defect == "unsampled_call":
        unsampled["model_calls"] = 1
    if defect == "selected_fallback":
        selected["model_validated"] = False
    if defect == "missing_turn":
        payload["turns"].pop()
    if defect == "wrong_commit":
        payload["tested_commit"] = "e" * 40
    if defect == "wrong_bundle":
        payload["bundle_sha256"] = "e" * 64
    if defect == "primary_delivery":
        unsampled["delivered_mode"] = "llm_analyst"
    if defect == "chosen_request_id":
        selected["request_id"] = "chosen"
    if defect == "duplicate_turn":
        payload["turns"][-1] = copy.deepcopy(payload["turns"][0])
    if defect == "boolean_only":
        payload = {"passed": True}
    record["checks"]["shadow_evaluation"].update(artifact(tmp_path, "shadow_evaluation", payload))
    assert any("shadow" in f for f in gate.validate_readiness(record, tmp_path))


def test_ready_record_still_needs_exact_final_owner_digest(tmp_path):
    record, _ = ready_record(tmp_path)
    record["approvals"]["launch"] = {
        "owner": "synthetic owner",
        "approved_at": "2026-01-01",
        **artifact(tmp_path, "launch", {}),
    }
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record))
    assert gate.validate_deployment_authorization(record, tmp_path, path, gate.sha256(path)) == []
    approved = gate.sha256(path)
    path.write_text(json.dumps(record) + " ")
    assert gate.validate_deployment_authorization(record, tmp_path, path, approved)


@pytest.mark.parametrize(
    "defect",
    [
        "disabled_loop",
        "launch_disabled_loop",
        "uncommitted",
        "replayed",
        "changed_denominator",
        "boolean_metric",
    ],
)
def test_stage_cannot_claim_a_legacy_stateless_or_reduced_cohort_pass(tmp_path, defect):
    record, payload = ready_record(tmp_path)
    if defect == "disabled_loop":
        record["pre_promotion_configuration"]["analyst_evidence_loop_enabled"] = False
    elif defect == "launch_disabled_loop":
        record["launch_configuration"]["analyst_evidence_loop_enabled"] = False
    elif defect in {"uncommitted", "replayed"}:
        payload["turns"][0]["state_committed" if defect == "uncommitted" else "replayed"] = (
            defect == "replayed"
        )
    elif defect == "changed_denominator":
        record["checks"]["evaluation"]["metrics"]["semantic_case_count"] = 49
    else:
        record["checks"]["evaluation"]["metrics"]["semantic_recall_at_5"] = True
    record["checks"]["shadow_evaluation"].update(artifact(tmp_path, "shadow_evaluation", payload))
    assert gate.validate_readiness(record, tmp_path)
