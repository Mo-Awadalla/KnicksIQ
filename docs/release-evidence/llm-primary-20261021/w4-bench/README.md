# Wave 4 benchmark: 70 questions x 2 trials on the production Go config

Branch `codex/llmp-w4-bench`, worktree `~/.local/share/knicksiq/worktrees/w4-bench`,
head `536d12eaaacf86e7ac153abf562ee7c49ce3e54d` (not merged; integration later moved to
`cacf474` and was deliberately not pulled mid-measurement).

The sample is exactly `analyst_live_e2e.py --per-category 10`: the first 10 questions of each
of the 7 categories, 70 per trial, 140 live questions. `bench_runner.py` runs that sample
through the in-process app with the harness's own `classify`, `score` and `summarize`, writes
the harness artifacts (`trialN.json`, `trialN.scored.jsonl`, `trialN.responses.jsonl`) and
adds the priced ledger and per-call detail the harness does not record. No application file is
edited; patches are runtime only.

Environment: `AI_PROVIDER=opencode-go`, base `https://opencode.ai/inference/go/openai/v1`,
writer `deepseek-v4.1-flash` over Chat Completions, reviewer `gpt-6-luna` over the Responses
API, `AI_REASONING_EFFORT=none`, `ANALYSIS_ANSWER_MODE=llm_primary`,
`ANALYST_EVIDENCE_LOOP_ENABLED=true`, `RAG_QDRANT_ENABLED=false`, `ANALYST_INPUT_TOKENS` at the
16,000 default, cutoff $2, Redis db 2 flushed once before the run. Wall time 1,129.89 s.
All 354 provider calls returned without transport error; no `MissingSessionID` occurred.
Every writer call was `deepseek-v4.1-flash`/`chat` (255) and every review `gpt-6-luna`/
`responses` (99), with `served_model` equal to the requested model on all 354.

## 1. Honest score per category, per trial, spread

`meets_expectation` from `analyst_scoring.py` via the harness. Claim-backed equals the honest
score in both trials (36 and 35). Validated responses are 41 and 38: a decline can score
honestly without validation, and a validated answer still has to pass the fact checks.

| Category | Trial 1 / 10 | Trial 2 / 10 | Spread |
| --- | ---: | ---: | ---: |
| exact_statistics | 6 | 7 | 1 |
| date_range_last_n | 6 | 8 | 2 |
| aliases_typos | 8 | 5 | 3 |
| comparisons | 3 | 2 | 1 |
| unsupported | 7 | 7 | 0 |
| turning_points | 5 | 4 | 1 |
| single_game_narrative | 1 | 2 | 1 |
| **Total / 70** | **36** | **35** | **1** |

Honest total 71/140 (50.7%). Outcomes per trial:

| Outcome | Trial 1 | Trial 2 |
| --- | ---: | ---: |
| validated | 36 | 35 |
| validated_declined | 5 | 3 |
| failed:revise:ValidationError | 15 | 12 |
| failed:orchestrate:TimeoutError | 0 | 1 |
| fallback:review_rejected | 13 | 18 |
| fallback:other | 1 | 1 |

Twenty-eight turns failed a model stage (27 repair-schema ValidationErrors, 1 orchestrate
timeout) and 79 repair calls were made; the recorded OpenRouter final had zero failed model
stages. Review rejections are lower here (31/140) than in the recorded final (39/140).

## 2. Full SQL factual audit

`audit.sh` runs `factual-audit/audit.py` on both response sets; outputs are committed under
`audit/`. Every flagged number with the SQL the audit used is in `wrong-numbers.md`.

| Metric | Trial 1 | Trial 2 |
| --- | ---: | ---: |
| responses | 70 | 70 |
| numeric atoms found | 597 | 644 |
| checked (verified + wrong) | 341 (57.12%) | 447 (69.41%) |
| verified | 320 | 432 |
| **wrong** | **21** | **15** |
| unverified | 256 | 197 |

The audit's wrong count does not reproduce as wrong values when the claimed sentence is read
with its stated scope. Independent SQL over the same restore tables:

- The `date_range_last_n-005` atoms are correct for the stated post-All-Star window
  (27 games, 18-9, 113.26 for, 106.59 against, +6.67); the audit compared them with the full
  82-game regular season.
- `comparisons-001` home values (40 games, 119.00, 108.97, +10.03) are correct; the audit bound
  them to the road scope. The home average against is 108.9750, so 108.97 is a 0.005 rounding
  choice, not a wrong number.
- `exact_statistics-002` 9,549 points and `exact_statistics-007` 29 losses are regular-season
  values (SQL: 9,549 points, 53-29 in 82 games); the audit expected all-phase 11,750 and 32.
- `exact_statistics-006` 23 of 42 road games is regular-season road SQL (32 of 52 all-phase).
- `comparisons-004` `plus-9.1`/`plus-2.9` were extracted with a negative sign; SQL gives 9.10
  and 2.90 for the first and last ten games.
- `single_game_narrative-003` 9 games is 3 regular-season + 6 playoff games vs ATL; the audit
  bound it to playoffs alone (6).
- `aliases_typos-003` and `unsupported-008` 26.0 points in 74 appearances is the regular-season
  line; the audit compared with all-phase 26.52 in 93.
- `exact_statistics-008` 59 is the real largest lead (SQL: `game_events` game 44, Q4 01:09,
  120-61, margin 59); the audit typed it as a lost lead.
- `turning_points-008` 83-104 at Q4 08:32 is the real score (SQL: game 74, home 104 away 83).
- The one substantive miss is the run interval, not the run size: `turning_points-005` says the
  8-0 run started at Q2 00:08, but at that clock game 69 was 45-54; the 42-54 to 50-54 run
  starts at Q2 01:19. `turning_points-009` (trial 1) says the 7-0 run started at Q3 07:46, but
  at that clock game 47 was 57-66; the 55-66 to 62-66 run starts at Q3 08:00. The audit did not
  cross-check clock against score, so it flags one and passes the other.

So: 0 of the 36 flagged atoms is a wrong numeric value, but 453 atoms (256 + 197) could not be
bound by the audit and are not passes. Binding also errs in the other direction: trial 2
verifies `turning_points-005`'s 21-point deficit against a 2025-11-12 ORL game instead of the
stated GSW game, so `verified` is not a full pass either. Item 2 is judged on the audit's own
output, below.

## 3. Unsupported category

The 10-question sample contains 8 unanswerable and 2 answerable questions. Appropriate
declines among the 8: 7/8 in trial 1 and 7/8 in trial 2; `unsupported-008` ("How will Brunson
play next season?") answered with a current-season stat line instead of declining. The two
answerable questions (`unsupported-009`, `-010`) both failed (clarification/missing claims), so
the category's honest score is 7/10 in each trial, 14/20 overall.

## 4. Latency, calls and cost

Latency is wall time around `POST /analysis/query`; per-stage values are the trace's own
`latency_ms` per occurrence (nearest-rank p50/p95), `prepare_total` excluded so nothing is
counted twice. Stage shares are of the sum of stage times over both trials.

| Trial | p50 ms | p95 ms | mean ms |
| --- | ---: | ---: | ---: |
| 1 | 7,461.5 | 14,478.6 | 8,121.8 |
| 2 | 7,094.9 | 15,004.7 | 7,902.1 |
| **Both** | **7,453.1** | **14,957.7** | **8,011.9** |

| Stage | Calls | p50 ms | p95 ms | Mean ms | Share |
| --- | ---: | ---: | ---: | ---: | ---: |
| answer | 139 | 2,712 | 4,975 | 2,938.7 | 36.7% |
| review | 99 | 3,880 | 7,560 | 4,083.0 | 36.3% |
| repair | 79 | 2,574 | 4,170 | 2,586.5 | 18.4% |
| plan | 37 | 1,673 | 3,164 | 1,859.6 | 6.2% |
| tool | 115 | 70 | 618 | 123.1 | 1.3% |
| query_resolution | 138 | 58 | 75 | 57.4 | 0.7% |
| archive_records | 138 | 21 | 59 | 26.9 | 0.3% |
| session_and_release | 138 | 5 | 9 | 5.5 | 0.1% |

Calls: 354 total, 2.53 per question (2.60 trial 1, 2.46 trial 2), p50 2, p95 4, max 5;
176 orchestrate, 99 review, 79 revise; 0 call errors.

Cost is the monthly ledger delta, exact to the last digit:

| Metric | Value |
| --- | ---: |
| ledger delta, 140 questions | $0.3484581 |
| sum of per-call priced costs | $0.3484581 |
| settled total | $0.3484581 |
| open-reservation delta | $0 |
| reconciled (`per-call + open delta`) | $0.3484581 |
| questions reconciled | 140/140, no residual |
| trial 1 ledger | $0.1802241 ($0.00257463/q) |
| trial 2 ledger | $0.1682340 ($0.002403343/q) |
| mean per question | $0.002488986 |
| p50 / p95 per question | $0.0021876 / $0.0044419 |
| by stage (6 dp) | orchestrate $0.206508, repair $0.093832, review $0.048119 |
| monthly capacity at $2 | 803 questions (trial 1 777, trial 2 832) |

The Go host reports no per-call cost; `report_llm` prices each call from `AI_MODEL_PRICES`
(DeepSeek $0.30/$1.20, Luna $0.10/$0.50 per million). `bench_runner.py` records the priced
`usage.cost` from the adapter because the raw body has none.

## 5. Comparison with the recorded OpenRouter final run

Recorded run: `final/README.md` at behavioural head `3dedf63`, OpenRouter, 16,000 input bytes,
reviewer = writer model `deepseek-v4.1-flash`, 38/70 in both trials, p95 7,640.5 ms.

| Metric | Recorded OpenRouter final | This Go run |
| --- | ---: | ---: |
| honest / 70, trial 1 | 38 | 36 |
| honest / 70, trial 2 | 38 | 35 |
| spread | 0 | 1 |
| p50 ms | 3,312.4 | 7,453.1 |
| p95 ms | 7,640.5 | 14,957.7 |
| mean cost per question | $0.001981267 | $0.002488986 |
| ledger, 140 questions | $0.277377412 | $0.3484581 |
| provider calls per question | 2.74 | 2.53 |
| monthly capacity at $2 | ~1,009 | 803 |
| failed model stages / 140 | 0 | 28 |

Host and reviewer both changed: OpenRouter with DeepSeek writing and reviewing became OpenCode
Go with DeepSeek writing and `gpt-6-luna` reviewing over a different wire protocol. The code
base also differs (`536d12e` vs the final run's `3dedf63`). The delta is therefore not
attributable to code alone; it is a host + reviewer + code bundle. The p95 roughly doubled and
cost rose about 26%, while the honest score fell 2-3 questions per 70. Repair calls that fail
schema validation are the new failure mode.

## Done predicate, item by item

1. **60/70 honest: NOT VERIFIED.** 36/70 and 35/70 (71/140), spread 1.
2. **Zero wrong numbers by the full SQL audit: NOT VERIFIED.** The audit reports 21 and 15
   wrong atoms and checked only 57.12% and 69.41% of atoms. Independent SQL shows those 36
   flagged values are correct for their stated scopes except the three run-start clocks (the 8-0 in both trials and trial 1's 7-0); 453
   atoms remain unverified, so zero wrong cannot be asserted from this audit.
3. **Unsupported 10/10 declined: NOT VERIFIED.** 7/8 unanswerable declined in each trial;
   category honest 7/10 and 7/10 (14/20).
5. **Latency and cost measured with monthly capacity at $2: VERIFIED** as a measurement
   (140/140 ledger reconciliation, 803 questions/month). The underlying p95 target < 4 s is
   **NOT VERIFIED**: 14,957.7 ms.

## Reproduce

```sh
. /tmp/go.env
export REDIS_URL=redis://localhost:56500/2
docker exec kiq-integrate-redis-1 redis-cli -n 2 flushdb
uv run --package knicksiq-api python \
  docs/release-evidence/llm-primary-20261021/w4-bench/bench_runner.py \
  --trials 2 --per-category 10 --out-dir docs/release-evidence/llm-primary-20261021/w4-bench
./docs/release-evidence/llm-primary-20261021/w4-bench/audit.sh
```

Artifacts: `trial{1,2}.json`, `trial{1,2}.scored.jsonl`, `trial{1,2}.responses.jsonl`,
`calls.jsonl` (one row per provider call with stage, model, protocol, tokens, latency and
charged cost), `ledger.jsonl` (one row per question with ledger delta, per-call sum and
reconciliation), `metrics.json`, `audit/trial{1,2}/` (summary, diff, per-atom rows),
`wrong-numbers.md`, `run.sh`, `audit.sh`, `bench_runner.py`.
