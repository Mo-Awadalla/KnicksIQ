"""Fail-closed stage and deployment authorization contracts (tests first).

Failure matrix: configuration-only shadow; absent/altered/wrong-candidate evidence;
missing/duplicate turns; chosen sample instead of fixed IDs; unsampled calls;
selected fallback counted as model success; primary delivery in shadow; altered
expectations; missing owner labels; readiness requiring premature launch approval;
missing/mismatched final record digest; legacy single-stage record accepted;
pure unsupported live questions forced into irrelevant archive/model answers.
New failure matrix: a forged or changed frozen contract; a clarification scored
as refusal (or reverse); sampled non-answer cases counted as model success; an
owner approval whose exact expectations hash differs from the frozen contract.
"""

import copy
import hashlib
import json

import pytest
from app.services import release_evidence as gate
from app.tests.test_release_evaluation import fixture_contract


def artifact(root, name, payload):
    path = root / (name + ".json")
    path.write_text(json.dumps(payload, sort_keys=True))
    return {"path": path.name, "sha256": gate.sha256(path)}


def ready_record(root):
    commit, bundle = "a" * 40, "b" * 64
    contract = fixture_contract()
    for case in contract["cases"]:
        if case["id"].startswith("unsupported-"):
            case["disposition"] = (
                "clarify"
                if case["id"] in {f"unsupported-{n:03}" for n in range(9, 15)}
                else "refuse"
            )
        elif case["id"] != "single_game_narrative-001":
            case["disposition"] = "answer"
            case["facts"] = [{"source": "synthetic fixture"}]
    contract_artifact = artifact(root, "frozen-contract", contract)
    expectations = contract_artifact["sha256"]
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
        "evaluation_contract": contract_artifact,
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
        approval_content = (
            {
                "owner": "synthetic owner",
                "approved_at": "2026-01-01",
                "expectations_sha256": expectations,
            }
            if name == "evaluation_labels"
            else {}
        )
        record["approvals"][name] = {
            "owner": "synthetic owner",
            "approved_at": "2026-01-01",
            **artifact(root, name + "-approval", approval_content),
        }
    cases = contract["cases"]
    ids = [item["id"] for item in cases]
    turns = []
    for item in cases:
        case_id = item["id"]
        request_id = hashlib.sha256(f"{expectations}:shadow:{case_id}".encode()).hexdigest()
        sampled = (
            int.from_bytes(hashlib.sha256(request_id.encode()).digest()[:4], "big") / (2**32 - 1)
            < 0.1
        )
        disposition = item["disposition"]
        answer = disposition == "answer"
        refusal = disposition == "refuse"
        turns.append(
            {
                "case_id": case_id,
                "request_id": request_id,
                "sampled": sampled,
                "model_calls": 2 if sampled and answer else 0,
                "model_validated": sampled and answer,
                "delivered_mode": (
                    "factual_fallback" if answer else "clarification" if not refusal else None
                ),
                "refused": refusal,
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
        "unsupported_archive",
        "clarify_as_refusal",
        "refuse_as_clarify",
    ],
)
def test_invalid_shadow_evidence_blocks_readiness(tmp_path, defect):
    record, payload = ready_record(tmp_path)
    selected = next(
        t for t in payload["turns"] if t["sampled"] and t["delivered_mode"] == "factual_fallback"
    )
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
    if defect == "unsupported_archive":
        unsupported = next(t for t in payload["turns"] if t["refused"])
        unsupported["refused"] = False
        unsupported["delivered_mode"] = "factual_fallback"
    if defect == "clarify_as_refusal":
        clarification = next(t for t in payload["turns"] if t["delivered_mode"] == "clarification")
        clarification["refused"] = True
        clarification["delivered_mode"] = None
    if defect == "refuse_as_clarify":
        refusal = next(t for t in payload["turns"] if t["refused"])
        refusal["refused"] = False
        refusal["delivered_mode"] = "clarification"
    if defect == "boolean_only":
        payload = {"passed": True}
    record["checks"]["shadow_evaluation"].update(artifact(tmp_path, "shadow_evaluation", payload))
    assert any("shadow" in f for f in gate.validate_readiness(record, tmp_path))


def test_shadow_uses_exact_frozen_contract_and_owner_signature(tmp_path):
    record, _ = ready_record(tmp_path)
    assert gate.validate_readiness(record, tmp_path) == []
    record["evaluation_contract"]["sha256"] = "0" * 64
    assert any("shadow" in f for f in gate.validate_readiness(record, tmp_path))
    record, _ = ready_record(tmp_path)
    record["approvals"]["evaluation_labels"].update(
        artifact(
            tmp_path,
            "evaluation_labels-approval",
            {
                "owner": "synthetic owner",
                "approved_at": "2026-01-01",
                "expectations_sha256": "0" * 64,
            },
        )
    )
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
