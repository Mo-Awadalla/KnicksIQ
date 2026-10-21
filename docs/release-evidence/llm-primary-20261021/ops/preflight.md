# llm_primary preflight: passing run and scope

Run on 2026-10-21 against the restored `2025-26.20260928.1` release with production settings,
Redis database 5, and the real provider configured but no live model call. Result: **25/25 checks
pass, exit code 0**. Artifact: `preflight.json`. Negative observations:
`preflight-failures.json`, `preflight-failure-cases.md`, `record-policy.md`,
`preflight-record-policy-fail.json` and `preflight-policy-broken-fail.json`.

## Command

```sh
uv run --package knicksiq-api python tools/release/preflight_llm_primary.py \
  --json-out docs/release-evidence/llm-primary-20261021/ops/preflight.json
```

The process environment must contain the production values named in the failure cases. The
artifact records presence, model names, totals, booleans, and the two probe answers; it does not
contain API keys, the Sentry DSN, the database URL, the Redis URL, or the IP hash secret.
`secrets_printed` is false.

## What the checks prove

- Configuration: required variables present, production environment, evidence loop enabled,
  OpenRouter with an allowlisted model, request timeout inside the analyst deadline, $2 cutoff,
  sane shadow rate, exact public CORS origin, trusted API host, format-valid Sentry DSN, and a
  non-default IP hash secret.
- Active release: `/health/ready` returns 200, has no required failures, and its `data_version`
  equals the active `dataset_releases` row.
- Budget ledger: `ai-budget:2026-10` exists, has no TTL, is numeric, and its reservations do not
  exceed its total.
- CORS and host filtering: the OPTIONS preflight returns the exact public origin and an unknown
  Host header returns 400.
- Kill switch: a separate app instance started with `ANALYSIS_ANSWER_MODE=deterministic` returns
  HTTP 200, `llm_validated=false`, `degraded=true`, cited facts, the budget-unavailable warning,
  53 wins and 29 losses recomputed from Postgres, and the words `regular season`. It must not
  assert the all-phase 69-32 record. A second request that asks for the overall record returns
  69 wins and 32 losses.
- Provider failure: an injected adapter exception returns HTTP 200 with cited deterministic facts,
  no validated model answer, and the same two record scopes.

## Record-scope oracle

Policy: a season-level record question defaults to the regular season (53-29) and the answer
states the phase; the overall record (69-32) appears only when the question says overall. The
preflight asserts both sides for the kill-switch and provider-failure probes. The oracle computes
both records from the active release, so it does not hard-code either value.

Two negative runs prove the oracle is not vacuous. `preflight-record-policy-fail.json` is the old
all-phase assertion applied to the same response; it fails. `preflight-policy-broken-fail.json`
runs the current oracle against a tree with the regular-season default temporarily disabled; it
fails. Method and observed evidence: `record-policy.md`. Both runs exercised only `kill_switch`,
made no provider request and charged nothing.

## Scope and cost

This is readiness, not a quality or latency measurement. The provider-failure probe makes two
model-free failed-call attempts and settles two reservations, which charged $0.02; it made no
provider request. The kill-switch probe is model-free and charged nothing. Quality is covered by
the live E2E workstream and latency by `capacity.md`.

Qdrant was disabled for the local run because it is optional for readiness and was not part of
this evidence. The Sentry DSN was a format-valid placeholder, so the check proves presence and
shape, not delivery. The run used the local restored database, not Neon, and Render was not
contacted.

With `--base-url` the same script probes a remote API. Configuration checks read the invoking
process environment unless `--skip-env` is set. The kill-switch and provider-failure probes need
control of the target process, so remote mode reports them as `skip` and the overall status is
`incomplete`; it does not claim a full pass.
