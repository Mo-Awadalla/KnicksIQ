# llm_primary preflight: passing run and scope

Run on 2026-10-21 against the restored `2025-26.20260928.1` release with production settings,
Redis database 6, and the real provider configured but no live model call. Result: **25/25 checks
pass, exit code 0**. Artifact: `preflight.json`. Negative observations: `preflight-failures.json`
and `preflight-failure-cases.md`.

## Command

```sh
uv run --package knicksiq-api python tools/release/preflight_llm_primary.py \
  --json-out docs/release-evidence/llm-primary-20261021/ops/preflight.json
```

The process environment must contain the production values named in the failure cases. The
artifact records presence, model names, totals, and booleans only; it does not contain API keys,
the Sentry DSN, the database URL, the Redis URL, or the IP hash secret. `secrets_printed` is false.

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
  and wins/losses recomputed from Postgres.
- Provider failure: an injected adapter exception returns HTTP 200 with cited deterministic facts,
  no validated model answer, and the same recomputed wins/losses.

## Scope and cost

This is readiness, not a quality or latency measurement. The provider-failure probe settles one
failed-call reservation, which charged $0.01; it made no provider request. The kill-switch probe is
model-free. Quality is covered by the live E2E workstream and latency by `capacity.md`.

Qdrant was disabled for the local run because it is optional for readiness and was not part of
this evidence. The Sentry DSN was a format-valid placeholder, so the check proves presence and
shape, not delivery. The run used the local restored database, not Neon, and Render was not
contacted.

With `--base-url` the same script probes a remote API. Configuration checks read the invoking
process environment unless `--skip-env` is set. The kill-switch and provider-failure probes need
control of the target process, so remote mode reports them as `skip` and the overall status is
`incomplete`; it does not claim a full pass.
