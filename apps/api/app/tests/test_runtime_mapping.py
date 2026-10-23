"""Source-binding failures specified before implementation.

Reject an unapproved manifest hash, foreign release/bundle, altered runtime
receipt, unknown or conflicting evidence ID, and derived receipts with missing
source receipts. Multi-source calculations must preserve all canonical sources;
identity resolution alone must never become answer-quality approval.
"""

import hashlib
import json

import pytest
from app.evaluation.release_runner import digest


def mapping_fixture(tmp_path):
    receipts = [
        {
            "evidence_id": f"release:game:{i}",
            "release_id": "release",
            "text": f"synthetic game {i}",
            "metadata": {},
        }
        for i in (1, 2)
    ]
    manifest = {
        "release_id": "release",
        "bundle_sha256": "a" * 64,
        "documents": {
            item["evidence_id"]: {
                "canonical_sources": [f"game:canonical-{i}"],
                "evidence_sha256": digest(item),
            }
            for i, item in enumerate(receipts, 1)
        },
    }
    path = tmp_path / "source-manifest.json"
    path.write_text(json.dumps(manifest))
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), receipts


def test_observed_receipts_require_exact_manifest_binding(tmp_path):
    from app.evaluation.runtime_mapping import resolve_runtime_mapping

    path, approved_hash, receipts = mapping_fixture(tmp_path)
    result = resolve_runtime_mapping(path, approved_hash, "release", "a" * 64, receipts)
    assert result["mapping"]["release:game:1"] == ["game:canonical-1"]
    assert result["source_manifest_sha256"] == approved_hash
    assert result["quality_approved"] is False
    (tmp_path / "resolved-mapping.json").write_text(json.dumps(result, indent=2))


@pytest.mark.parametrize(
    "fault", ["manifest_hash", "bundle", "release", "changed_receipt", "unknown", "collision"]
)
def test_mapping_rejects_unbound_evidence(tmp_path, fault):
    from app.evaluation.runtime_mapping import resolve_runtime_mapping

    path, approved_hash, receipts = mapping_fixture(tmp_path)
    release, bundle = "release", "a" * 64
    if fault == "manifest_hash":
        path.write_text(path.read_text() + " ")
    elif fault == "bundle":
        bundle = "b" * 64
    elif fault == "release":
        release = "different-release"
    elif fault == "changed_receipt":
        receipts[0]["text"] = "altered"
    elif fault == "unknown":
        receipts[0]["evidence_id"] = "unmapped"
    else:
        receipts.append({**receipts[0], "text": "conflicting duplicate"})
    with pytest.raises(ValueError):
        resolve_runtime_mapping(path, approved_hash, release, bundle, receipts)


def test_calculation_preserves_every_source_and_checks_recipe(tmp_path):
    from app.evaluation.runtime_mapping import resolve_runtime_mapping

    path, approved_hash, receipts = mapping_fixture(tmp_path)
    refs = [r["evidence_id"] for r in receipts]
    claim = {"release_id": "release", "subject_id": "team:NYK", "metric_id": "points", "value": 225}
    identity = (
        "calculation:"
        + hashlib.sha256(
            json.dumps(["release", "team:NYK", "points", refs, 225], sort_keys=True).encode()
        ).hexdigest()
    )
    calculation = {
        "evidence_id": identity,
        "release_id": "release",
        "text": "225 points",
        "metadata": {"source_evidence_ids": refs},
    }
    result = resolve_runtime_mapping(
        path, approved_hash, "release", "a" * 64, receipts + [calculation], {identity: claim}
    )
    assert result["mapping"][identity] == ["game:canonical-1", "game:canonical-2"]
    with pytest.raises(ValueError):
        resolve_runtime_mapping(
            path,
            approved_hash,
            "release",
            "a" * 64,
            receipts[1:] + [calculation],
            {identity: claim},
        )
    with pytest.raises(ValueError):
        resolve_runtime_mapping(
            path,
            approved_hash,
            "release",
            "a" * 64,
            receipts + [calculation],
            {identity: {**claim, "value": 999}},
        )
