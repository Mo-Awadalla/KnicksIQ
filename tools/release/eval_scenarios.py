"""Adversarial regression scenarios for the evaluation scorer, written before the scorer.

Every scenario drives the real ``app.evaluation.cli`` (or the standalone
``tools/release/eval_runner.py``) as a subprocess against synthetic label
artifacts, crafted runtime responses and local fake HTTP endpoints. Nothing
contacts a provider, Qdrant, Redis, PostgreSQL or a remote host, and nothing
here is a label approval or a real measurement.

Run: uv run --package knicksiq-api python tools/release/eval_scenarios.py [name ...]
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from eval_scenarios_budget import (
    scenario_budget_approval_rejections,
    scenario_budget_concurrency_cap,
    scenario_budget_failure_consumes_attempt,
    scenario_budget_reused_approval_restart,
    scenario_budget_seal_fences_and_origin_denied,
    scenario_budget_unbound_and_tampered_config,
)
from eval_scenarios_citations import (
    scenario_calculation_receipt_reuse,
    scenario_calculation_receipts,
    scenario_missing_trace_and_rank,
    scenario_possession_document_receipts,
    scenario_receipt_prefix_is_not_identity,
)
from eval_scenarios_collection import (
    scenario_collect_disabled_flag_only,
    scenario_collect_ignores_ambient_proxy,
    scenario_collect_profile,
    scenario_collect_rejects_remote_base_url,
    scenario_provider_stage_in_collect_refused,
)
from eval_scenarios_context import (
    scenario_context_changed_rejected,
    scenario_context_clean,
    scenario_context_dropped_rejected,
    scenario_context_frozen_identity,
    scenario_context_omitted_rejected,
    scenario_context_proposal_override_rejected,
    scenario_context_substituted_rejected,
    scenario_context_whitespace_rejected,
)
from eval_scenarios_facts import (
    scenario_attribution_inputs,
    scenario_clean,
    scenario_decimal_display_precision,
    scenario_extra_claim,
    scenario_integer_mismatch,
    scenario_scoreline_and_signed_facts,
    scenario_unattributed_numeric,
)
from eval_scenarios_guards import (
    scenario_runner_cleanup_escalates,
    scenario_runner_db_url_matrix,
    scenario_runner_failed_startup_preserves_evidence,
    scenario_runner_readiness_ignores_proxy,
    scenario_runner_readiness_rejects_foreign_listener,
    scenario_runner_rejects_remote_db,
)
from eval_scenarios_integrity import (
    scenario_abstention_content_checked,
    scenario_empty_review_assertions_rejected,
    scenario_request_case_mismatch,
    scenario_request_identity_required,
    scenario_required_fact_coverage_gated,
    scenario_response_digest_mismatch_not_credited,
    scenario_review_span_not_in_response_rejected,
    scenario_unresolved_assertion_blocks,
    scenario_unsupported_review_gates_additions,
)
from eval_scenarios_labels import (
    scenario_changed_question_text_rejected,
    scenario_fabricated_approval_blocks,
    scenario_freeze_mismatch_blocks,
    scenario_labels_digest_not_inferred,
    scenario_malformed_labels_digest,
    scenario_real_dataset,
    scenario_semantic_membership_changed,
    scenario_stale_identity_review_rejected,
    scenario_unverifiable_labels_digest,
)
from eval_scenarios_projection import (
    scenario_games_count_display,
    scenario_games_count_projected,
    scenario_games_count_scope,
    scenario_margin_extreme_projection,
    scenario_scope_windows_from_population,
    scenario_scoreline_scope_projection,
)
from eval_scenarios_proof import (
    scenario_collect_requires_live_proof,
    scenario_proof_protocol_roundtrip,
)
from eval_scenarios_proof_score import (
    scenario_collect_service_proven,
    scenario_score_rejects_unproven_rows,
)
from eval_scenarios_provenance import (
    scenario_additional_claim_other_subject,
    scenario_calculation_arithmetic_checked,
    scenario_calculation_evidence_required,
    scenario_calculation_population_bounded,
    scenario_denominator_not_sample_size,
    scenario_foreign_release_receipt_rejected,
    scenario_invalid_trace_no_behavior_credit,
    scenario_legacy_trace_does_not_supply_narrative_gold,
    scenario_per_claim_support_required,
    scenario_scoreline_extra_field_fails,
    scenario_source_content_verified,
)
from eval_scenarios_review_failures import (
    scenario_legacy_semantic_behavior_is_not_recall,
    scenario_omitted_fact_review_is_measured,
    scenario_wrong_disposition_review_is_measured,
)
from eval_scenarios_reviews import (
    scenario_disposition_separation,
    scenario_independence_from_flags,
    scenario_missing_and_duplicate_observations,
    scenario_provider_trace_in_disabled_run,
    scenario_review_decisions,
    scenario_stale_review_decisions,
)
from eval_scenarios_semantics import (
    scenario_displayed_precision_additions,
    scenario_player_population_checked,
    scenario_runtime_metric_forms_pass,
    scenario_season_mismatch_fails,
    scenario_subject_unverifiable_blocks,
    scenario_team_subject_substitution,
    scenario_unmapped_references_do_not_verify,
    scenario_window_direction_required,
)
from eval_scenarios_service import (
    scenario_collect_service_needs_guard_proof,
    scenario_collect_service_run_stamp,
    scenario_runner_service_refuses_without_inputs,
    scenario_score_service_requires_attestation,
)

SCENARIOS: dict[str, Callable[[Path], list[str]]] = {
    "legacy_semantic_behavior_is_not_recall": scenario_legacy_semantic_behavior_is_not_recall,
    "omitted_fact_review_is_measured": scenario_omitted_fact_review_is_measured,
    "wrong_disposition_review_is_measured": scenario_wrong_disposition_review_is_measured,
    "clean": scenario_clean,
    "context_clean": scenario_context_clean,
    "context_omitted_rejected": scenario_context_omitted_rejected,
    "context_dropped_rejected": scenario_context_dropped_rejected,
    "context_changed_rejected": scenario_context_changed_rejected,
    "context_substituted_rejected": scenario_context_substituted_rejected,
    "context_proposal_override_rejected": scenario_context_proposal_override_rejected,
    "context_frozen_identity": scenario_context_frozen_identity,
    "context_whitespace_rejected": scenario_context_whitespace_rejected,
    "proof_protocol_roundtrip": scenario_proof_protocol_roundtrip,
    "collect_requires_live_proof": scenario_collect_requires_live_proof,
    "collect_service_proven": scenario_collect_service_proven,
    "score_rejects_unproven_rows": scenario_score_rejects_unproven_rows,
    "integer_mismatch": scenario_integer_mismatch,
    "decimal_display_precision": scenario_decimal_display_precision,
    "extra_claim": scenario_extra_claim,
    "games_count_projected": scenario_games_count_projected,
    "games_count_scope": scenario_games_count_scope,
    "games_count_display": scenario_games_count_display,
    "unattributed_numeric": scenario_unattributed_numeric,
    "attribution_inputs": scenario_attribution_inputs,
    "receipt_prefix_is_not_identity": scenario_receipt_prefix_is_not_identity,
    "calculation_receipts": scenario_calculation_receipts,
    "calculation_receipt_reuse": scenario_calculation_receipt_reuse,
    "missing_trace_and_rank": scenario_missing_trace_and_rank,
    "disposition_separation": scenario_disposition_separation,
    "independence_from_flags": scenario_independence_from_flags,
    "missing_and_duplicate_observations": scenario_missing_and_duplicate_observations,
    "provider_trace_in_disabled_run": scenario_provider_trace_in_disabled_run,
    "review_decisions": scenario_review_decisions,
    "stale_review_decisions": scenario_stale_review_decisions,
    "margin_extreme_projection": scenario_margin_extreme_projection,
    "scoreline_and_signed_facts": scenario_scoreline_and_signed_facts,
    "scoreline_scope_projection": scenario_scoreline_scope_projection,
    "possession_document_receipts": scenario_possession_document_receipts,
    "malformed_labels_digest": scenario_malformed_labels_digest,
    "unverifiable_labels_digest": scenario_unverifiable_labels_digest,
    "real_dataset": scenario_real_dataset,
    "collect_profile": scenario_collect_profile,
    "budget_concurrency_cap": scenario_budget_concurrency_cap,
    "budget_failure_consumes_attempt": scenario_budget_failure_consumes_attempt,
    "budget_unbound_and_tampered_config": scenario_budget_unbound_and_tampered_config,
    "budget_reused_approval_restart": scenario_budget_reused_approval_restart,
    "budget_approval_rejections": scenario_budget_approval_rejections,
    "budget_seal_fences_and_origin_denied": scenario_budget_seal_fences_and_origin_denied,
    "collect_service_needs_guard_proof": scenario_collect_service_needs_guard_proof,
    "collect_service_run_stamp": scenario_collect_service_run_stamp,
    "score_service_requires_attestation": scenario_score_service_requires_attestation,
    "runner_service_refuses_without_inputs": scenario_runner_service_refuses_without_inputs,
    "provider_stage_in_collect_refused": scenario_provider_stage_in_collect_refused,
    "collect_ignores_ambient_proxy": scenario_collect_ignores_ambient_proxy,
    "collect_rejects_remote_base_url": scenario_collect_rejects_remote_base_url,
    "collect_disabled_flag_only": scenario_collect_disabled_flag_only,
    "runner_rejects_remote_db": scenario_runner_rejects_remote_db,
    "runner_db_url_matrix": scenario_runner_db_url_matrix,
    "runner_readiness_ignores_proxy": scenario_runner_readiness_ignores_proxy,
    "runner_readiness_rejects_foreign_listener": scenario_runner_readiness_rejects_foreign_listener,
    "runner_cleanup_escalates": scenario_runner_cleanup_escalates,
    "runner_failed_startup_preserves_evidence": scenario_runner_failed_startup_preserves_evidence,
    "required_fact_coverage_gated": scenario_required_fact_coverage_gated,
    "response_digest_mismatch_not_credited": scenario_response_digest_mismatch_not_credited,
    "unsupported_review_gates_additions": scenario_unsupported_review_gates_additions,
    "unresolved_assertion_blocks": scenario_unresolved_assertion_blocks,
    "empty_review_assertions_rejected": scenario_empty_review_assertions_rejected,
    "review_span_not_in_response_rejected": scenario_review_span_not_in_response_rejected,
    "abstention_content_checked": scenario_abstention_content_checked,
    "request_identity_required": scenario_request_identity_required,
    "request_case_mismatch": scenario_request_case_mismatch,
    "fabricated_approval_blocks": scenario_fabricated_approval_blocks,
    "freeze_mismatch_blocks": scenario_freeze_mismatch_blocks,
    "changed_question_text_rejected": scenario_changed_question_text_rejected,
    "semantic_membership_changed": scenario_semantic_membership_changed,
    "stale_identity_review_rejected": scenario_stale_identity_review_rejected,
    "labels_digest_not_inferred": scenario_labels_digest_not_inferred,
    "calculation_evidence_required": scenario_calculation_evidence_required,
    "calculation_arithmetic_checked": scenario_calculation_arithmetic_checked,
    "per_claim_support_required": scenario_per_claim_support_required,
    "foreign_release_receipt_rejected": scenario_foreign_release_receipt_rejected,
    "invalid_trace_no_behavior_credit": scenario_invalid_trace_no_behavior_credit,
    "legacy_trace_is_not_narrative_gold": scenario_legacy_trace_does_not_supply_narrative_gold,
    "denominator_not_sample_size": scenario_denominator_not_sample_size,
    "unmapped_references_do_not_verify": scenario_unmapped_references_do_not_verify,
    "additional_claim_other_subject": scenario_additional_claim_other_subject,
    "scoreline_extra_field_fails": scenario_scoreline_extra_field_fails,
    "team_subject_substitution": scenario_team_subject_substitution,
    "subject_unverifiable_blocks": scenario_subject_unverifiable_blocks,
    "player_population_checked": scenario_player_population_checked,
    "scope_windows_from_population": scenario_scope_windows_from_population,
    "window_direction_required": scenario_window_direction_required,
    "season_mismatch_fails": scenario_season_mismatch_fails,
    "runtime_metric_forms_pass": scenario_runtime_metric_forms_pass,
    "displayed_precision_additions": scenario_displayed_precision_additions,
    "source_content_verified": scenario_source_content_verified,
    "calculation_population_bounded": scenario_calculation_population_bounded,
}


def main(argv: list[str]) -> int:
    selected = argv or sorted(SCENARIOS)
    unknown = [name for name in selected if name not in SCENARIOS]
    if unknown:
        print(f"unknown scenarios: {', '.join(unknown)}", file=sys.stderr)
        return 2
    failures = 0
    for name in selected:
        with tempfile.TemporaryDirectory(prefix=f"eval-{name}-") as raw:
            directory = Path(raw)
            try:
                problems = SCENARIOS[name](directory)
            except Exception as exc:  # noqa: BLE001
                problems = [f"{type(exc).__name__}: {exc}"]
            if problems:
                failures += 1
                print(f"FAIL {name}")
                for problem in problems:
                    print(f"     {problem}")
            else:
                print(f"ok   {name}")
    print(f"\n{len(selected) - failures}/{len(selected)} scenarios passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
