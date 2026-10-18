# Release evidence

Record: `2025-26-verified-parity`
Tested commit: `e003db2d7f179c8d490d90155f260ec0eeb31620`
Deployment gate: **BLOCKED**

Generated from release-record.json; this view is not approval evidence.

- active_archive_identity: missing passing evidence for tested commit
- evaluation: missing passing evidence for tested commit
- evaluation_services_disabled: missing passing evidence for tested commit
- production_router_contracts: missing passing evidence for tested commit
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
- evaluation_labels: missing owner approval bound to content
- launch: missing owner approval bound to content

Agents verify every report against canonical evidence. The owner
approves the template, exceptions, and final content-hash-bound audit
summary. Reviewed flags do not establish approval; unresolved checks block release.

Render rebuilds the tested commit. Artifacts are not claimed identical to CI builds.
Rollback coordinates restoration of services, dataset activation and alias mappings;
not atomically. Stop promotion and alert the owner on any restoration failure.
