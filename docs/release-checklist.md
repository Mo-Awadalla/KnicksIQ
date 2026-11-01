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

The gate validates `ANALYSIS_ANSWER_MODE` and `ANALYSIS_SHADOW_SAMPLE_RATE`
in `render.yaml`, not just the record. The deployment command reads that blueprint
from `--tested-root` while resolving evidence artifacts from the evidence checkout.
A missing or invalid blueprint blocks promotion.

The published October 28 observations remain in
[the historical readiness snapshot](release-evidence/readiness-20261028.json).
They do not replace current-worktree checks, exact-commit CI or owner approval.

The complete provider-disabled evaluation is a candidate diagnostic, not a release pass.
Its 120-case denominators remain fixed. The 302-fact enriched proposal is still
unapproved and unfrozen, and all 50 original semantic targets are unresolved.
The recorded owner decision keeps unresolved semantic cases release-blocking.
Local signed-service tests use a fake upstream and never establish provider quality.
Do not create approval or freeze records, set semantic targets, or promote the answer mode.

The October 30 public-source check recalculates all 302 proposed factual values.
It uses ESPN box scores for 100 games and Basketball Reference for the remaining game,
with fresh NBA pages recorded separately as same-origin consistency checks.
The turnover comparison needs its player-attributed definition stated explicitly because
Basketball Reference team totals also include unassigned team turnovers.
Local evidence is saved in
`release-artifacts/production-completion-20261030/independent-web-label-validation.json`.
This verifies values over declared source populations, not every question interpretation,
semantic relevance target, owner approval or candidate whole-answer review.

Repeatable production scenario (isolated Postgres, Redis, production-profile API, and
built web app on ports `19430`–`19433`, no provider traffic):

```sh
uv run --frozen --all-packages python tools/release/production_e2e.py
```

Still owed as environment verification, not merely code review:

- An independent provider-side monthly limit exists and is consistent with the $2
  `OPENROUTER_MONTHLY_CUTOFF_USD` application cutoff. A missing Redis ledger restarts
  at zero by recorded owner decision, so the provider limit is the only independent stop.
- The Render edge's forwarded scheme and client address reach the container: without
  the scheme every public request is redirected, and without the address every user
  shares one rate-limit identity.
- The runtime database role holds only `SELECT` on application tables and views.
- The deployed container reports healthy through its own health probe, and
  `/health/ready` returns 200 with the expected data version. Liveness alone is not a
  go-live gate.
- Public directory endpoints serve only active validated release membership; staged-only
  players and teams are absent and detail requests 404.

See `docs/production-runbook.md` for the exact commands and procedures.

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
