# Live smoke, 2026-10-21 (corrected cutoff, two trials)

Lead correction: the `OPENROUTER_MONTHLY_CUTOFF_USD=0.30` fence was wrong because reservations stay
charged until settled. The corrected cutoff is 2 USD on Redis db 1. The earlier 0.30 artifacts are
renamed `*-cutoff030-invalidated.*` and are not counted as evidence.

Command (same for both trees), existing flags only:

```text
uv run python tools/release/analyst_live_e2e.py --per-category 1 --out <out>.json
```

Environment: local release `2025-26.20260928.1`, `DB_URL` on port 55500, `REDIS_URL` db 1,
`ANALYSIS_ANSWER_MODE=llm_primary`, `ANALYST_EVIDENCE_LOOP_ENABLED=true`,
`OPENROUTER_MONTHLY_CUTOFF_USD=2`, Qdrant off.

## Outcomes per question, two trials per tree

`Y` marks `meets_expectation`; `n` does not.

| Question | final3 (10-18) | head t1 | head t2 | base t1 | base t2 |
| --- | --- | --- | --- | --- | --- |
| exact_statistics-001 | validated Y | validated Y | validated Y | validated Y | validated Y |
| date_range_last_n-001 | validated Y | review_rejected n | review_rejected n | RuntimeError n | RuntimeError n |
| comparisons-001 | validated_declined n | RuntimeError n | review_rejected n | RuntimeError n | ValidationError n |
| single_game_narrative-001 | validated_declined n | RuntimeError n | review_rejected n | review_rejected n | review_rejected n |
| turning_points-001 | validated_declined n | review_rejected n | RuntimeError n | review_rejected n | review_rejected n |
| aliases_typos-001 | validated Y | review_rejected n | review_rejected n | review_rejected n | RuntimeError n |
| unsupported-001 | validated_declined Y | review_rejected n | validated_declined Y | review_rejected n | review_rejected n |
| meets_expectation | 4/7 | 1/7 | 2/7 | 1/7 | 1/7 |

Head spread: 1 to 2 of 7 across two trials. Base spread: 1 of 7 in both. The two trees differ by at
most one question, and both are far below the 10-18 result.

## RuntimeError rows under cutoff 2

The corrected cutoff did not remove the `RuntimeError` rows, so they are not budget failures. A
diagnostic run captured the exception at the reviewer and repair calls:

```text
RuntimeError('AI provider response omitted message content')
```

That is raised by `report_llm.py` when the provider returns choices without message content. These
rows are provider failures and are counted as misses. Rows from the 0.30 run remain invalidated by
the cutoff instruction and are excluded; the four new trial files are the counted evidence.

## Reading

`prompt-schema-diff.json` proves the orchestrator prompt and full `Action` schema are byte-identical
to base. `dispatch-parity-base.json` and `dispatch-parity-head.json` are identical for all six tools
and all pre-check branches. Under today's provider, both trees fail the same way on the same
questions, including the stable `exact_statistics-001` validation in all four trials. The live
no-regression comparison against final3 is inconclusive because reviewer rejection and empty
provider content are much more frequent than on 10-18, on the unchanged base tree as well.

Model questions spent: 49 total. 19 on the invalidated 0.30 run (including diagnostics), 28 in the
four two-trial runs, and 2 diagnostics for the RuntimeError cause. Redis db 1 ledger is $0.595 with
the 2 USD cutoff.
