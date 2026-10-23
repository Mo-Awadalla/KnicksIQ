# Release evidence

Record: `2025-26-verified-parity`
Tested commit: `ade107fe17b3a8ff0e59632bd45b3826e4499068`
Readiness gate: **BLOCKED**

Generated from release-record.json; this view is not approval evidence.

- active_archive_identity: missing passing evidence for tested commit
- report_audit: missing passing evidence for tested commit
- evaluation: missing passing evidence for tested commit
- evaluation_services_disabled: missing passing evidence for tested commit
- production_router_contracts: missing passing evidence for tested commit
- rollback_snapshot: missing passing evidence for tested commit
- evaluation: semantic_recall_at_5 must be >= 0.95
- evaluation: exact_numeric_correctness must be >= 1.0
- evaluation: canonical_entity_correctness must be >= 1.0
- evaluation: citation_correctness must be >= 0.95
- evaluation: paraphrase_success must be >= 0.95
- evaluation: correct_abstention_rate must be >= 1.0
- evaluation: all 120 reviewed labels required
- evaluation: missing ranked retrieval traces
- evaluation: original 50-case semantic cohort required
- evaluation_services_disabled: exact_numeric_correctness must be >= 1.0
- evaluation_services_disabled: canonical_entity_correctness must be >= 1.0
- evaluation_services_disabled: citation_correctness must be >= 0.95
- evaluation_services_disabled: paraphrase_success must be >= 0.95
- evaluation_services_disabled: correct_abstention_rate must be >= 1.0
- evaluation_services_disabled: all 120 reviewed labels required
- evaluation_services_disabled: original 50-case semantic cohort required
- template: missing owner approval bound to content
- exceptions: missing owner approval bound to content
- report_audit: missing owner approval bound to content
- evaluation_labels: missing owner approval bound to content
- evaluation contract: missing valid hash-bound frozen expectations

Agents verify every report against canonical evidence. The owner
approves the template, exceptions, and final content-hash-bound audit
summary. Reviewed flags do not establish approval; unresolved checks block release.

Render rebuilds the tested commit. Artifacts are not claimed identical to CI builds.
Rollback coordinates restoration of services, dataset activation and alias mappings;
not atomically. Stop promotion and alert the owner on any restoration failure.
