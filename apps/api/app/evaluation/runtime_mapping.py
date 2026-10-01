"""Resolve observed evidence against an independently verified source manifest.

The manifest must be built from the exact isolated runtime's source records and
approved bundle before scoring. Its expected hash comes from that verification,
not from this resolver. This resolves identity/recipe only, never relevance,
semantic correctness, population completeness or label approval.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def resolve_runtime_mapping(
    manifest_path: Path,
    verified_manifest_sha256: str,
    release_id: str,
    bundle_sha256: str,
    evidence: list[dict],
    calculation_claims: dict | None = None,
) -> dict:
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != verified_manifest_sha256:
        raise ValueError("Source manifest differs from verified hash")
    manifest = json.loads(raw)
    if manifest.get("release_id") != release_id or manifest.get("bundle_sha256") != bundle_sha256:
        raise ValueError("Source manifest release/bundle mismatch")
    documents = manifest["documents"]
    observed: dict[str, dict] = {}
    for receipt in evidence:
        ref = receipt["evidence_id"]
        if receipt.get("release_id") != release_id:
            raise ValueError("Foreign runtime evidence release")
        if ref in observed and _digest(observed[ref]) != _digest(receipt):
            raise ValueError("Conflicting runtime evidence identity")
        observed[ref] = receipt
    mapping: dict[str, list[str]] = {}
    for ref, receipt in observed.items():
        if ref.startswith("calculation:"):
            continue
        expected = documents.get(ref)
        if not expected or expected.get("evidence_sha256") != _digest(receipt):
            raise ValueError("Unknown or altered runtime receipt")
        sources = expected.get("canonical_sources")
        if (
            not isinstance(sources, list)
            or not sources
            or any(not isinstance(s, str) or not s for s in sources)
        ):
            raise ValueError("Missing canonical source identity")
        mapping[ref] = list(dict.fromkeys(sources))
    for ref, receipt in observed.items():
        if not ref.startswith("calculation:"):
            continue
        claim = (calculation_claims or {}).get(ref)
        source_refs = receipt.get("metadata", {}).get("source_evidence_ids")
        if (
            not claim
            or claim.get("release_id") != release_id
            or not isinstance(source_refs, list)
            or not source_refs
            or any(not isinstance(source, str) or source not in mapping for source in source_refs)
        ):
            raise ValueError("Calculation has unverified or missing source receipts")
        recipe = [release_id, claim["subject_id"], claim["metric_id"], source_refs, claim["value"]]
        expected_ref = (
            "calculation:" + hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
        )
        if expected_ref != ref:
            raise ValueError("Calculation recipe identity mismatch")
        mapping[ref] = list(
            dict.fromkeys(source for source_ref in source_refs for source in mapping[source_ref])
        )
    return {
        "release_id": release_id,
        "bundle_sha256": bundle_sha256,
        "source_manifest_sha256": verified_manifest_sha256,
        "observed_evidence_sha256": _digest(evidence),
        "mapping": mapping,
        "quality_approved": False,
        "scope": "observed source identities and calculation recipes only",
    }
