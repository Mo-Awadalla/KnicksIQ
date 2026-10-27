# Ops evidence: llm_primary, 2026-10-21

Scope: launch-configuration reconciliation, preflight, capacity, and the rollback drill procedure.
No deployment, no push, no production settings change, no release-record approval change.

- `preflight.md`: passing preflight method and scope.
- `preflight.json`: 25/25 checks pass, exit 0, secrets absent.
- `record-policy.md`: record-scope oracle, with both forced-failure methods.
- `preflight-record-policy-fail.json`: negative run using the old all-phase assertion, expected fail.
- `preflight-policy-broken-fail.json`: negative run with the regular-season default disabled,
  expected fail.
- `docs-consistency.json`: launch-mode consistency check output.
- Launch-mode check: `tools/release/check_launch_mode_consistency.py` compares `render.yaml`,
  `docs/release-checklist.md` and `docs/analyst-evidence-loop.md`.
- `preflight-remote.json`: four target checks pass against a real local HTTP server using
  `--base-url`.
- `preflight-failure-cases.md` and `preflight-failures.json`: 25 isolated broken-input runs, all
  expected failures observed.
- `capacity.md`, `capacity.json`, `capacity.rows.jsonl`: 40 live questions with per-question
  charged cost, tokens, calls, and latency, plus the $2 cutoff calculation and the measured
  latency gate failure.
- Authoritative launch configuration and owner decisions:
  `docs/release-checklist.md#intended-launch-configuration`.
- Rollback drill: `docs/production-runbook.md#rollback-drill-llm_primary-to-deterministic-or-shadow`.

Live questions spent: 40 of 40. Provider spend in the capacity run: $0.03624128. The final preflight
failure probe made two model-free attempts and settled two reservations, $0.02. The two
record-policy negative runs made no provider request and charged nothing. No other live model
calls were made.
