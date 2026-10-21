# Live smoke, 2026-10-21

Command (both trees), one question per category via the existing flag:

```text
uv run --package knicksiq-api python tools/release/analyst_live_e2e.py \
  --per-category 1 --out <out>.json
```

Environment: local release `2025-26.20260928.1`, `DB_URL` on port 55500, `REDIS_URL` db 1,
`ANALYSIS_ANSWER_MODE=llm_primary`, `ANALYST_EVIDENCE_LOOP_ENABLED=true`,
`OPENROUTER_MONTHLY_CUTOFF_USD=0.30`, Qdrant off.

## Results

| Question | final3 (10-18) | head (registry) | base control |
| --- | --- | --- | --- |
| exact_statistics-001 | validated, meets | failed:orchestrate:RuntimeError | validated, meets |
| date_range_last_n-001 | validated, meets | fallback:review_rejected | validated, meets |
| comparisons-001 | validated_declined | fallback:review_rejected | fallback:review_rejected |
| single_game_narrative-001 | validated_declined | failed:revise:RuntimeError | fallback:review_rejected |
| turning_points-001 | validated_declined | failed:revise:RuntimeError | failed:revise:RuntimeError |
| aliases_typos-001 | validated, meets | failed:orchestrate:ValidationError | fallback:review_rejected |
| unsupported-001 | validated_declined, meets | fallback:review_rejected | fallback:review_rejected |
| meets_expectation | 4/7 | 0/7 | 2/7 |

Head: `live-smoke.json`, `live-smoke.responses.jsonl`. Base control:
`live-smoke-base-control.json`, `live-smoke-base-control.responses.jsonl`.

## Reading

Neither tree matches the 2026-10-18 outcomes under today's provider conditions. The base tree,
which contains none of this refactor, also drops the two questions it still passed. The head run's
three `RuntimeError` entries are `Budget unavailable` from transient reservation failures; one
later single-question rerun of exact_statistics-001 on the head tree validated (reviewer verdict
supported, no warnings), and another rerun was rejected, so the reviewer outcome is stochastic on
this provider today.

The refactor cannot explain the drift: `prompt-schema-diff.json` proves the orchestrator prompt
(sha256 `98edb2b2...`) and the complete `Action` schema are byte-identical, and
`dispatch-parity-base.json` / `dispatch-parity-head.json` are identical for all six tools and all
pre-check branches. The live comparison against final3 is therefore inconclusive as a no-regression
measure today; it is not evidence of a branch regression.

Model questions spent: 7 head + 7 base control + 5 single-question diagnostics = 19, plus the
earlier flag-off run that made no model calls. Redis db 1 monthly ledger moved from $0.008 to
$0.268, under the $0.30 cutoff.
