"""Independent archive receipt and arithmetic verification for prompt-quality evaluation."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.evaluation.arithmetic import ClaimView, prove
from app.evaluation.arithmetic_box import PLAYER_FIELDS
from app.evaluation.arithmetic_window import check_window_membership
from app.evaluation.mapping import load_mapping
from app.evaluation.mapping_citation import claim_view, player_canonical_id, player_display_name
from app.evaluation.observations import TypedClaim, canonical_digest
from app.evaluation.observations_records import evidence_registry

FLOW = Path(__file__).resolve().parent
VERSION = "2025-26.20260928.1"
BUNDLE = "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"


class GraderBlocked(RuntimeError):
    """The archive, a required proof, or the judge is unavailable or unverifiable."""


def _mapping():
    directory = Path(os.environ.get("RATCHET_MAPPING_DIR", str(FLOW / "local")))
    path = directory / "runtime-mapping.json"
    report_path = directory / "runtime-mapping-verification.json"
    try:
        report = json.loads(report_path.read_text())
        mapping = load_mapping(path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise GraderBlocked(f"Cannot load verified local archive mapping: {exc}") from exc
    expected = {"games": 101, "player_game_stats": 2748, "team_game_stats": 202, "period_scores": 816}
    if (report.get("passed") is not True or report.get("bundle_sha256") != BUNDLE
            or report.get("version") != VERSION or report.get("collections") != expected
            or report.get("database_host") != "127.0.0.1" or report.get("problems")
            or mapping.version != VERSION or report.get("release_id") != mapping.release_id):
        raise GraderBlocked("Local mapping verification report does not match the approved archive")
    actual = {name: sum(row.collection == name and row.source_row is not None
                        for row in mapping.rows.values()) for name in expected}
    if actual != expected or any(row.release_id != mapping.release_id for row in mapping.rows.values()):
        raise GraderBlocked(f"Local mapping has incomplete or foreign source rows: {actual}")
    return mapping


def _claims_and_proofs(response: dict[str, Any], mapping: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Prove typed claims independently; invalid candidate data cannot earn credit."""
    registry, registry_problems = evidence_registry(response)
    failures = list(registry_problems)
    verified = []
    seen: dict[str, dict[str, Any]] = {}
    citations = response.get("citations") or []
    if not isinstance(citations, list):
        return [], failures + ["citations_not_list"]
    for citation in citations:
        if not isinstance(citation, dict) or not isinstance(citation.get("metadata"), dict):
            failures.append("malformed_citation")
            continue
        raw = citation["metadata"].get("claim")
        if raw is None:
            continue
        if not isinstance(raw, dict):
            failures.append("malformed_claim")
            continue
        try:
            claim = TypedClaim.from_dict(raw)
        except (ValueError, TypeError, KeyError) as exc:
            failures.append(f"malformed_claim:{exc}")
            continue
        previous = seen.get(claim.claim_id)
        if previous is not None:
            if previous != raw:
                failures.append("conflicting_claim_id")
            continue
        seen[claim.claim_id] = raw
        if claim.release_id != VERSION or claim.season != "2025-26":
            failures.append("claim_foreign_release_or_season")
            continue
        if not claim.subject_id or not claim.supporting_evidence_ids:
            failures.append("claim_missing_subject_or_receipt")
            continue
        direct_player_stat = (
            claim.subject_id.startswith("player:")
            and (claim.metric_id == "box_score" or claim.metric_id in PLAYER_FIELDS)
            and not any(ref.startswith("calculation:") for ref in claim.supporting_evidence_ids)
        )
        sources = []
        calculations = []
        bad = False
        for reference in claim.supporting_evidence_ids:
            resolution = mapping.resolve_citation(
                reference, None if direct_player_stat else raw, registry=registry
            )
            if resolution.unverified:
                missing_receipt_content = {
                    "calculation_content_unverified", "calculation_sources_unverified",
                    "citation_content_unverified",
                }
                if set(resolution.unverified) <= missing_receipt_content:
                    failures.extend(resolution.unverified)
                    bad = True
                    continue
                raise GraderBlocked(f"Unsupported proof for {claim.metric_id}: {', '.join(resolution.unverified)}")
            if not resolution.resolved:
                failures.extend(resolution.problems or ("unresolved_citation",))
                bad = True
                continue
            if reference.startswith("calculation:"):
                calculations.append(resolution)
                refs = resolution.sources
            else:
                refs = (reference,)
            for ref in refs:
                source_resolution = mapping.resolve_citation(ref, None)
                record = registry.get(ref)
                if not source_resolution.resolved or record is None or record.release_id != VERSION:
                    failures.append("source_receipt_or_registry_missing")
                    bad = True
                    continue
                for canonical in source_resolution.canonical_ids:
                    row = mapping.rows.get(canonical)
                    if row is None or row.source_row is None:
                        raise GraderBlocked(f"No projected archive row for receipt {ref}")
                    if ((record.row_sha256 is not None and record.row_sha256 != row.row_sha256)
                            or (record.source_row is not None and canonical_digest(record.source_row) != row.row_sha256)):
                        failures.append("source_snapshot_mismatch")
                        bad = True
                        continue
                    if canonical not in {x[0] for x in sources}:
                        sources.append((canonical, row))
        if bad:
            continue
        # Calculation receipts re-prove their formula using mapping snapshots. For a
        # plain row receipt, explicitly run the same arithmetic engine: identity
        # resolution alone never proves a numeric assertion.
        if calculations:
            if len(calculations) != 1 or len(claim.supporting_evidence_ids) != 1:
                raise GraderBlocked(f"Ambiguous calculation receipt set for {claim.metric_id}")
            record = registry[claim.supporting_evidence_ids[0]]
            view = claim_view(mapping, raw, claim.subject_id, claim.metric_id, claim.value, record)
        else:
            view = ClaimView(metric=claim.metric_id, value=claim.value, subject=claim.subject_id,
                             game_ids=claim.game_ids, window=claim.window, eligibility=claim.eligibility,
                             baseline_claim_ids=claim.baseline_claim_ids, sample_size=claim.sample_size,
                             denominator=claim.denominator,
                             player_name=player_display_name(claim.subject_id, mapping.player_names))
        snapshots = [r.source_row for _, r in sources]
        if direct_player_stat:
            fields = ({"points", "rebounds", "assists", "turnovers"}
                      if claim.metric_id == "box_score" else {claim.metric_id})
            values = claim.value if claim.metric_id == "box_score" else {claim.metric_id: claim.value}
            player = player_canonical_id(claim.subject_id, mapping.player_canonical_ids)
            valid = (
                len(snapshots) == 1 and len(sources) == 1 and not calculations
                and sources[0][1].collection == "player_game_stats"
                and isinstance(values, dict) and set(values) == fields
                and all(type(values[key]) in (int, float) and values[key] == snapshots[0].get(key)
                        for key in fields)
                and player is not None and str(snapshots[0].get("nba_player_id")) == str(player)
                and set(claim.game_ids) == {sources[0][1].game_id}
                and claim.sample_size == 1 and claim.denominator is None
                and snapshots[0].get("minutes", 0) > 0
            )
            if not valid:
                failures.append("box_score_snapshot_or_subject_mismatch")
                continue
            verified.append({"claim": raw, "recipe": "single_game_box_snapshot",
                             "sources": [{"id": key, "collection": row.collection,
                                          "row": row.source_row} for key, row in sources]})
            continue
        proof = prove(view, rows=snapshots, collections=[r.collection for _, r in sources],
                      player=player_canonical_id(claim.subject_id, mapping.player_canonical_ids),
                      population=mapping.population)
        if proof.status == "unverifiable":
            raise GraderBlocked(f"Unsupported proof for {claim.metric_id}: {proof.reason or proof.recipe or 'unknown recipe'}")
        if proof.status != "verified":
            failures.extend(proof.problems or ("arithmetic_invalid",))
            continue
        membership = check_window_membership(view, snapshots, mapping.population)
        window_verified = membership is not None and not membership.reason and not membership.problems
        kinds = {row.collection for _, row in sources}
        archive_complete = False
        if kinds == {"games"}:
            archive_complete = {key for key, _ in sources} == {
                key for key, row in mapping.rows.items() if row.collection == "games"
            }
        elif kinds == {"player_game_stats"}:
            player = player_canonical_id(claim.subject_id, mapping.player_canonical_ids)
            archive_complete = player is not None and {key for key, _ in sources} == {
                key for key, row in mapping.rows.items()
                if row.collection == "player_game_stats" and row.source_row is not None
                and str(row.source_row.get("nba_player_id")) == str(player)
                and row.source_row.get("minutes", 0) > 0
            }
        if (not proof.population_cited and not window_verified and not archive_complete
                and len({r.game_id for _, r in sources}) > 1):
            failures.append("population_completeness_unverified")
            continue
        recipe = proof.recipe
        verified.append({"claim": raw, "recipe": recipe,
                         "sources": [{"id": key, "collection": row.collection,
                                      "row": row.source_row} for key, row in sources]})
    return verified, failures
