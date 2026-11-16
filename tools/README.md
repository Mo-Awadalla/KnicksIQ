# Tools

## Season-chat evaluation

Run commands from the repository root through `uv run --package knicksiq-api`.

- `python tools/release/eval_scenarios.py` runs synthetic integrity, numeric, entity, arithmetic, label, budget and proof scenarios. It is not a provider-quality measurement.
- `python tools/release/eval_runner.py --help` describes isolated collection and scoring. Collection uses `/chat/turns`, real earlier user commands, per-case access tokens and settled revisions. The service profile requires explicit bounded approval and private ledger attestation.
- `python tools/release/privacy_boundary_check.py` checks body limits, message bounds, the chat token boundary and telemetry scrubbing without a provider.
- `python tools/release/telemetry_sdk_check.py` checks SDK telemetry scrubbing without a live telemetry destination.
- `python tools/release/readiness.py --help` describes provider-free release health and private canonical SQL row verification. It requires an explicit loopback `--dsn` and the direct listening API worker `--api-pid`. The worker's explicit `DB_URL` must match. It reuses `runtime_mapping.verify_restore` inside a read-only PostgreSQL snapshot and never reads a public archive export or accepts a stored mapping as row proof.
- `python tools/release/analyst_live_e2e.py --help` describes bounded real chat collection from a loopback API. Human review is required; completion is not a factual or voice grade.
- `python tools/release/stress.py --help` describes concurrent chat turns and readiness readers. It spends provider budget and requires separate authorization. Historical `analyst_p95_ms` and `archive_p95_ms` names remain for release-record continuity.
- `python tools/release/runtime_mapping.py --help` describes the private canonical SQL mapping used by unchanged arithmetic checks. Narrative collection still calls `AnalystTools` directly.

Public replies never carry citations, analytics, tool traces or provider metadata.
`citation_receipt_correctness` retains its original answer-case denominator and reports
`inapplicable: public citations retired; owner-approved rubric migration pending`.
It has no passing value. Release remains blocked pending that approval.
Numeric values, question IDs, semantic membership and other release thresholds are unchanged.

The evaluation-only proof wrapper forwards SSE chunks immediately and appends a final
`evaluation_proof` event. The signature covers the command, status and normalized final
reply/snapshot/delta count. It does not establish network timing or provider quality.
Production does not expose this proof event.

## Retired tools

`release/shadow_isolation_probe.py` and the entire `release/prompt_quality/` runner were
deleted with shadow sampling and `AnalystLoop`. `release/provenance_positive_control.py`
was deleted because its only purpose was the removed public-citation contract.
The obsolete public provider-stage collection rejection scenario was deleted because
chat streams do not disclose private provider calls. Private ledger checks remain.

Internal ingestion, report audit, release authorization, hooks and canonical label tools
remain separate from the public chat surface. No tool command grants deployment,
production data mutation or paid-provider authorization.
