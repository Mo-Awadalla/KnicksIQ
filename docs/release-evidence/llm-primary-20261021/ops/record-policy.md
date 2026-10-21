# Record-scope oracle: passing run and forced failures

Policy: a season-level record question defaults to the regular season and the answer states the
phase. With the restored `2025-26.20260928.1` release, the regular-season record is 53-29 and the
all-phase record is 69-32. The all-phase record appears only when the question says overall.

The preflight probes both scopes. `kill_switch` sends "What was the Knicks record this season?" and
"What was the Knicks record overall this season?" against a deterministic app. `provider_failure`
sends the same two questions with an adapter that raises. Each probe requires:

- cited `wins` and `losses` claims equal to the SQL record for that scope;
- the record numbers present in the answer;
- `regular season` stated in the season-level answer, and no all-phase record in it;
- `llm_validated=false` and the expected degradation signals.

The oracle computes both records from the active release. It does not hard-code 53-29 or 69-32.

## Passing run

`preflight.json` was recorded with the full check set: 25 pass, 0 fail and exit code 0. The two
record probes hold `db_record` 53-29 and `db_overall_record` 69-32, and the answers match.

## Forced failure 1: old all-phase assertion

The previous oracle asserted 69-32 for the season-level question. To prove the new oracle detects
that case, `REGULAR_SEASON` in `tools/release/preflight/runtime_checks.py` was temporarily set to
`None`, which makes the season-level probe expect the all-phase record. The run used
`--only kill_switch` and wrote `preflight-record-policy-fail.json`.

Observed: one fail, exit code 1. The answer says "Knicks regular season wins: 53 over 82 archived
games. Knicks regular season losses: 29 over 82 archived games." while the expected record in the
artifact is 69-32. The constant was restored immediately.

## Forced failure 2: policy broken

The updated oracle was then run against a tree with the regular-season default temporarily
disabled in `query_resolution.py` (`elif season_type is None and season_level and False`). This is
a real policy break, not an oracle change. The run used `--only kill_switch` and wrote
`preflight-policy-broken-fail.json`.

Observed: one fail, exit code 1. The season-level answer becomes
"Knicks wins: 69 over 101 archived games. Knicks losses: 32 over 101 archived games.", which
matches the all-phase record and omits `regular season`. The oracle rejects it. The policy line was
restored immediately.

## Reproduction

```sh
uv run --package knicksiq-api python tools/release/preflight_llm_primary.py \
  --only kill_switch \
  --json-out docs/release-evidence/llm-primary-20261021/ops/preflight-policy-broken-fail.json
```

The process environment must hold the production values from `preflight-failure-cases.md`. Use a
fresh high-entropy `IP_HASH_SECRET` for an isolated run so the shared minute rate-limit bucket is
empty. Neither forced-failure run made a provider request or charged the ledger. The passing full
run settled the provider-failure probe's reservations as documented in `preflight.md`.
