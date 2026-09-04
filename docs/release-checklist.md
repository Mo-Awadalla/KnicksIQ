# Release verification

Use the [versioned release record](release-evidence/release-record.json) and
[generated owner review view](release-evidence/release-record.md) as the source of
release status. Historical local preflight results do not establish current deployment readiness.

Generate the view and run the fail-closed gate from the repository root:

```sh
uv run --package knicksiq-api python -m app.services.release_evidence docs/release-evidence/release-record.json --render
```

The launch configuration is 10% shadow with deterministic answers delivered to users. Automatic
Render deployments stay disabled. Both NOW workstreams block deployment. NEXT and LATER are
outside this release gate and hosting remains unchanged.

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
