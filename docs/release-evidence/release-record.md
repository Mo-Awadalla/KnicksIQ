# Release evidence

Record: `2025-26-verified-parity`
Tested commit: `unverified`
Deployment gate: **BLOCKED**

Generated from release-record.json; this view is not approval evidence.

- missing exact tested Git commit
- missing data hash
- missing bundle hash
- active_archive_identity: missing passing evidence for tested commit
- report_audit: missing passing evidence for tested commit
- retrieval_targets: missing passing evidence for tested commit
- retrieval_filters: missing passing evidence for tested commit
- evaluation: missing passing evidence for tested commit
- evaluation_services_disabled: missing passing evidence for tested commit
- production_router_contracts: missing passing evidence for tested commit
- backend: missing passing evidence for tested commit
- frontend: missing passing evidence for tested commit
- migrations_loader: missing passing evidence for tested commit
- security: missing passing evidence for tested commit
- desktop_mobile_keyboard: missing passing evidence for tested commit
- accessibility: missing passing evidence for tested commit
- warm_load: missing passing evidence for tested commit
- shadow_dependencies: missing passing evidence for tested commit
- rollback_snapshot: missing passing evidence for tested commit
- evaluation: semantic_recall_at_5 must be >= 0.95
- evaluation: exact_numeric_correctness must be >= 1.0
- evaluation: canonical_entity_correctness must be >= 1.0
- evaluation: citation_correctness must be >= 0.95
- evaluation: paraphrase_success must be >= 0.95
- evaluation: correct_abstention_rate must be >= 1.0
- evaluation: all 120 reviewed labels required
- evaluation: missing ranked retrieval traces
- evaluation_services_disabled: exact_numeric_correctness must be >= 1.0
- evaluation_services_disabled: canonical_entity_correctness must be >= 1.0
- evaluation_services_disabled: citation_correctness must be >= 0.95
- evaluation_services_disabled: paraphrase_success must be >= 0.95
- evaluation_services_disabled: correct_abstention_rate must be >= 1.0
- evaluation_services_disabled: all 120 reviewed labels required
- warm latency/concurrency/error gates not met
- accessibility: zero serious/critical findings required
- template: missing owner approval bound to content
- exceptions: missing owner approval bound to content
- report_audit: missing owner approval bound to content
- evaluation_labels: missing owner approval bound to content
- launch: missing owner approval bound to content
- missing coordinated rollback targets

Agents verify every report against canonical evidence. The owner
approves the template, exceptions, and final content-hash-bound audit
summary. Reviewed flags do not establish approval; unresolved checks block release.

Render rebuilds the tested commit. Artifacts are not claimed identical to CI builds.
Rollback coordinates restoration of services, dataset activation and alias mappings;
not atomically. Stop promotion and alert the owner on any restoration failure.
