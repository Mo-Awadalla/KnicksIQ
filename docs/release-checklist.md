# Release verification

Use the [versioned release record](release-evidence/release-record.json) and
[generated owner review view](release-evidence/release-record.md) as the source of
release status. Historical local preflight results do not establish current deployment readiness.

Generate the view and run the fail-closed gate from the repository root:

```sh
uv run --package knicksiq-api python -m app.services.release_evidence docs/release-evidence/release-record.json --render
```

## Intended launch configuration

This section is the single authoritative statement of the intended launch. Other documents link
here instead of restating the mode.

The launch serves `ANALYSIS_ANSWER_MODE=llm_primary` with `ANALYST_EVIDENCE_LOOP_ENABLED=true`,
`ANALYSIS_SHADOW_SAMPLE_RATE=0.1` retained only for explicit shadow drills (primary turns are
never sampled), `OPENROUTER_MONTHLY_CUTOFF_USD=2`, an allowlist containing only the configured
model, and a configured Sentry DSN. Users receive validated evidence-loop answers. Any provider,
budget, validation or optional-dependency failure degrades to deterministic cited facts. These are
the values declared by `render.yaml` and asserted by `test_render_blueprint_enables_the_grounded_ai_configuration`.

Pre-promotion verification is a separate, earlier state: `answer_mode=shadow`,
`shadow_sample_rate=0.1`, deterministic delivery. The `configuration` block in
`release-evidence/release-record.json` records that pre-promotion state. It is not the launch
configuration, and the current validator still rejects a record whose configuration is not
shadow/0.1. Resolving that policy split is an owner decision.

Owner-only decisions:

- Approve the policy change in `release-policy-proposal.md` that separates the pre-promotion
  shadow gate from the llm_primary launch check. Until approved, the validator keeps requiring
  shadow/0.1 in the record.
- Authorize real-provider spend and the $2 monthly cutoff.
- Approve any exception to a failed quantitative release gate, including the measured analyst
  latency gate.
- Approve evaluation labels, the scoring rubric, the release record digest and any exception.
- Authorize deploy and activation, and any production settings change, including a rollback
  drill against production.

Everything else in this document is agent-verifiable and does not require owner sign-off.
Automatic Render deployments stay disabled. Both NOW workstreams block deployment. NEXT and LATER
are outside this release gate and hosting remains unchanged.

Agents verify all reports against canonical evidence. The owner approves the corrected template,
exceptions and final hash-bound audit summary rather than each write-up. A reviewed flag alone
is insufficient. Evaluation labels require owner approval in batches. Do not fill approvals on
the owner's behalf. The tested commit, audit/evaluation/data/bundle hashes, environment checks,
deployment IDs and rollback snapshot belong in the record.

Application deployment rebuilds the exact tested Git commit on existing Render services;
these rebuilt artifacts are not asserted identical to CI artifacts. Capture both existing
application deployments, active data version and alias mapping before promotion. Smoke-test
both resulting services. Restore every changed component on failure; coordinated restoration
is not atomic. Stop promotion and alert the owner if any restoration fails.
