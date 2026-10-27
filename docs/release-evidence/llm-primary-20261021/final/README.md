# Final phase: input budget A/B, factual audit, held-out, preflight

Branch `final` from `codex/llmp-integration` at `93d1a2e`. Behavioural head for every run:
`3dedf63` (`analyst_input_tokens` default 16,000, `le=32000`). Local restored release
`2025-26.20260928.1` (101 games), real OpenRouter provider, `AI_REASONING_EFFORT=none`,
`OPENROUTER_MONTHLY_CUTOFF_USD=2`, Redis db 15 only. Live questions spent: 398 of 400.

The bundled `ab_runner.py` imports the committed harness and scorer, so the sample and the
honest `meets_expectation` check are exactly `analyst_live_e2e.py --per-category 10`. It
patches four runtime seams to record what the harness does not: per-question ledger delta and
settlement reconciliation, wall latency, execution-failure messages, and writer claim packing
(`build_payload` / `request_model` wrappers). No application file is edited by the runner.

## Step 1: input budget A/B

70 questions, 2 trials per config (140 per config), 280 total. Redis db 15 was flushed with
`redis-cli -p 56500 -n 15 flushdb` immediately before each configuration: before 8,000,
before 16,000, before the 8,000 drop-count repair, and before the held-out run. A first
8,000-byte smoke question exposed a missing `ANALYST_EVIDENCE_LOOP_ENABLED=true`; a second
smoke validated the instrumented path. Both smoke questions are counted in the total.

| Metric | 8,000 | 16,000 |
| --- | ---: | ---: |
| honest meets_expectation, trial 1 / 70 | 27 | 38 |
| honest meets_expectation, trial 2 / 70 | 27 | 38 |
| spread between trials | 0 | 0 |
| honest meets_expectation, total / 140 | 54 | 76 |
| claim-backed meets_expectation, total | 54 | 76 |
| validated (`llm_validated`) / 140 | 94 (67.1%) | 99 (70.7%) |
| fallback review_rejected | 39 | 39 |
| fallback other | 2 | 2 |
| failed model stages | 5 | 0 |
| p50 latency, ms | 3,260.5 | 3,312.4 |
| p95 latency, ms | 6,223.9 | 7,640.5 |
| mean latency, ms | 3,472.5 | 3,666.2 |
| ledger delta, 140 questions | $0.155872027 | $0.277377412 |
| mean cost per question | $0.001113372 | $0.001981267 |
| open reservations after | $0 | $0 |
| reconciliation (`settled + open delta`) | exact, 140/140 | exact, 140/140 |
| provider calls per question | 2.93 | 2.74 |
| input bytes p95 / cap | 7,973 / 8,000 | 15,557 / 16,000 |
| input bytes max | 7,999 | 16,000 |
| JSON bytes per prompt token, median | 3.91 | 3.50 |
| packing exceptions, same 56 questions | 2 | 0 |
| writer drop events, same 56 questions | 78 | 24 |
| claims dropped, same 56 questions | 459 | 124 |
| questions with a dropped claim, same 56 | 38 / 56 | 12 / 56 |
| largest drop in one writer call, same 56 | 16 claims | 15 claims |
| claims dropped per question, same 56 | 8.2 | 2.2 |
| claims dropped, full 140 | not captured (see below) | 274 |
| questions with a dropped claim, full 140 | not captured | 30 / 140 |

Failed stages at 8,000: 2 `review:ValueError`, 2 `orchestrate:ValueError`, 1
`orchestrate:ValidationError`. At 16,000: none.

Per category, honest passes per 10-question category (trial 1 / trial 2):

| Category | 8,000 | 16,000 |
| --- | --- | --- |
| exact_statistics | 8 / 7 | 9 / 8 |
| date_range_last_n | 3 / 5 | 6 / 6 |
| aliases_typos | 5 / 4 | 4 / 5 |
| comparisons | 2 / 2 | 5 / 5 |
| unsupported | 8 / 7 | 7 / 8 |
| turning_points | 1 / 2 | 4 / 4 |
| single_game_narrative | 0 / 0 | 3 / 2 |

### Instrumentation defect and the 8,000 drop-count repair

In the first 8,000 run the per-question `drops` and `overflows` lists were stored by reference
and cleared in place, so every row serialized the last question's list. Quality, latency and
cost in that run are unaffected; the packing and budget-event counts are not usable. The
runner now stores `list(...)` copies (committed here). Packing counts for 8,000 come from a
fresh balanced run of the first 8 questions per category at 8,000 (56 questions, 1 trial,
`budget-8000-drops`); the 16,000 comparable columns are those same 56 ids filtered from its
first trial. The full 16,000 run supplies the 140-question drop counts.
`budget-8000.summary.json` also carries `budget_events.exceeds_input_budget: 0` from the same
aliased list; ignore that block and use `budget-8000-drops.summary.json`.

The repair run at 8,000: 2 packing exceptions, both `Required review/action context exceeds
input budget`; no `Required model input exceeds budget` (the schema-aware mandatory check)
fired. 22/56 honest passes, ledger $0.052514626 for 56 questions, reconciled. The same 56 at
16,000: 0 exceptions, 34/56 honest passes, 124 claims dropped.

### Decision

16,000 wins the stated order. Quality first: +11 honest passes per 70 in both trials, with
zero spread, and every failed model stage disappears. p95 latency is second: +1.4 s (neither
config meets the 4 s gate; the reviewer dominates). Cost is third: +78 percent mean per
question. The cap still binds at 16,000 (p95 15,557 of 16,000; 274 claims still dropped), so
16,000 reduces the drop rate rather than removing it. Default set to 16,000, bound raised to
32,000; commit `3dedf63` carries this table.

## Step 2: independent factual audit

Audit: `docs/release-evidence/llm-primary-20261021/factual-audit/audit.py` over both 16,000
trials, run from temporary copies so the committed 2026-10-18 verdict files are not
overwritten. Outputs are in `audit-16000-trial1/` and `audit-16000-trial2/`.

| Verdict | Trial 1 | Trial 2 |
| --- | ---: | ---: |
| CORRECT | 31 | 31 |
| INCORRECT | 1 | 1 |
| UNSUPPORTED_CLAIM | 3 | 3 |
| DECLINE_APPROPRIATE | 7 | 8 |
| DECLINE_MISSED_ANSWER | 27 | 26 |
| INSUFFICIENT | 1 | 1 |
| numeric claims checked / failed | 45 / 0 | 45 / 0 |

One primary INCORRECT in each trial. Per the brief this is a release blocker; it is reported,
not fixed. Neither is a wrong number: zero of the 45 re-evaluated numeric claims failed.

1. Trial 1, `unsupported-007` ("Did the Knicks win yesterday?"). Verdict INCORRECT because the
   policy spec forbids the literal `2025-12-21` (`checks_policy_20261021.py:195-203` sets
   `verdict=DECLINE_APPROPRIATE`, `decline_verdict=DECLINE_APPROPRIATE`,
   `forbidden_terms=["2025-12-21"]`), and `audit.py` forces INCORRECT whenever a forbidden
   term appears, even inside an otherwise appropriate decline. The answer states the archive
   ends `2026-06-13` (SQL: latest game 2026-06-13) and then quotes a true historical line:
   Brunson 47 points on 2025-12-21 (SQL: `player_game_stats` 47 points, `games.game_date`
   2025-12-21). The trial-2 answer to the same question omits the historical example and is
   DECLINE_APPROPRIATE. The label is a false positive on a correctly framed true date.

2. Trial 2, `aliases_typos-010` ("What was NY's worst collpase?"). Verdict INCORRECT because
   the required term `19` is absent and the decline detector does not match the wording "does
   not identify". The required fact is true: NYK led by 19 on 2025-12-31 at SAS (game 33) and
   lost 132-134 (SQL: `min(score_margin) = -19`, final margin 2). Trial 1 answered the same
   question with "doesn't contain", matched the detector, and was labelled
   DECLINE_MISSED_ANSWER. Both are declined misses with true numbers; the primary label flips
   on phrasing.

The audit's finding-level list is spec-static: `audit.py` copies each spec's `findings`
without re-matching its quote against today's answer, so the "21 findings" printed in
`unsupported.md` are annotations of the 2026-10-18 responses, not measurements of these
answers. The primary verdicts and re-evaluated claims above are the measured result.

## Step 3: held-out set, once

Run after `3dedf63`. Redis db 15 flushed first. Command uses the committed default, so
`ANALYST_INPUT_TOKENS` is not set. Compared with the committed baseline in
`docs/release-evidence/llm-primary-20261021/scoring/heldout-60.json`.

| Metric | Committed baseline | This run |
| --- | ---: | ---: |
| mode | offline rescore of committed responses | live |
| honest meets_expectation / 60 | 5 (8.3%) | 20 (33.3%) |
| claim-backed / 60 | 5 | 20 |
| old screen / 60 | 6 | 45 |
| answerable / 50 | 4 | 11 |
| unsupported / 10 | 1 | 9 |
| ledger delta | not recorded | $0.160063287 |
| mean cost per question | not recorded | $0.002667721 |

By category (baseline -> this run): aliases_typos 0 -> 5 of 8, comparisons 0 -> 0 of 8,
date_range_last_n 1 -> 2 of 9, exact_statistics 2 -> 1 of 9, single_game_narrative 1 -> 0 of 8,
turning_points 0 -> 3 of 8, unsupported 1 -> 9 of 10.

Interpretation caveat: 35 of 60 rows fail on `required_facts`. Several held-out expectations are
all-phase, while the app now answers the regular season with its phase stated. Examples
verified in SQL: expected `points per game 116.34` is all 101 games, the answer's `116.45` is
the 82 regular-season games; expected `home losses 12` is 49 home games, the answer's `10` is
40 regular-season home games. `heldout-exact_statistics-001` asks for the regular-season
record explicitly and passes with 53-29. The comparison to 5/60 uses the same scorer and still
shows +15; the 80 percent held-out predicate is not met.

The factual audit does not apply: every held-out id lacks a registered check, so the audit
returns 60/60 INSUFFICIENT (`heldout-60.audit-summary.md`). No check was added after seeing
the results.

## Step 4: preflight

`tools/release/preflight_llm_primary.py` in-process on `3dedf63`, production-shaped
environment, local DB, Redis db 15. Result: 23 pass, 2 fail, 0 skip (`preflight.json`,
`secrets_printed=false`).

The two failures are the record-count oracle the brief predicted:

- `kill_switch` and `provider_failure` both return HTTP 200, `llm_validated=false`,
  `degraded=true` or a warning, cited facts, and the deterministic answer
  `Knicks regular season wins: 53 ... losses: 29`.
- `fetch_team_record` counts all 101 games and asserts `69-32`, so `claim_metrics {53,29}`
  against `db_record {69,32}` fails both checks. SQL confirms both records: all-phase 69-32,
  regular season 53-29, and the policy default is regular season with the phase stated.
- Every other assertion in both probes passes. Another agent is fixing the oracle; the
  preflight was not edited.

## Questions spent

2 smoke + 140 (8,000) + 140 (16,000) + 56 (8,000 drop repair) + 60 held-out = 398 of 400.
Preflight made no provider request; its provider-failure probe settles one $0.01 reservation
without calling the model.

## Done predicate (llmp-context.md), item by item

1. 60/70 on the 70-question set and 80 percent on held-out: NOT VERIFIED. Best is 38/70
   (54.3 percent) at 16,000, and 20/60 (33.3 percent) held-out. Both beat their precedents
   (37/70 old screen on the 2026-10-18 run; 5/60 honest held-out baseline), but the predicate
   is not met.
2. Independent factual audit, zero incorrect and zero unsupported: NOT VERIFIED. Zero numeric
   claims failed, but each trial has one primary INCORRECT (two mechanisms above) and three
   primary UNSUPPORTED_CLAIM responses; 27 and 26 answerable questions were declined.
3. Unsupported category 10/10 declined: NOT VERIFIED. 15 of 20 across the two 70-set trials
   (7.5 of 10 per trial); 9 of 10 on held-out.
4. Backend suite green: VERIFIED on `3dedf63` (`TEST_MODE=true uv run pytest apps packages
   tools/report_audit`: 439 passed; `uv run ruff check apps packages migrations`: all checks
   passed; `ruff format --check`: 244 files already formatted; `pyright`: 0 errors, 0
   warnings). Web was not run (no web change in this task).
5. Cost and latency measured with a monthly capacity number at $2: VERIFIED for this config.
   p50 3,312.4 ms, p95 7,640.5 ms, mean $0.001981 per question. At $2 that is about 1,009
   questions per month at the 70-set mix (750 per month at the harder held-out rate of
   $0.002668). Provider routing variance moves the per-question cost; see the cost evidence.

## Commands

```sh
git worktree add ~/.local/share/knicksiq/worktrees/final -b final 93d1a2e
uv sync --all-packages --all-extras --dev

# A/B (repeat with ANALYST_INPUT_TOKENS=16000 and --label budget-16000)
redis-cli -p 56500 -n 15 flushdb
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
REDIS_URL=redis://localhost:56500/15 ANALYSIS_ANSWER_MODE=llm_primary \
ANALYST_EVIDENCE_LOOP_ENABLED=true AI_REASONING_EFFORT=none \
OPENROUTER_MONTHLY_CUTOFF_USD=2 ANALYST_INPUT_TOKENS=8000 \
uv run --package knicksiq-api python \
docs/release-evidence/llm-primary-20261021/final/ab_runner.py \
--label budget-8000 --trials 2 --out-dir docs/release-evidence/llm-primary-20261021/final

# 8,000 drop-count repair (fresh db flush first)
# same environment with --label budget-8000-drops --trials 1 --per-category 8

# held-out, once (fresh db flush first; no ANALYST_INPUT_TOKENS)
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
REDIS_URL=redis://localhost:56500/15 ANALYSIS_ANSWER_MODE=llm_primary \
ANALYST_EVIDENCE_LOOP_ENABLED=true AI_REASONING_EFFORT=none \
OPENROUTER_MONTHLY_CUTOFF_USD=2 \
uv run --package knicksiq-api python tools/release/analyst_live_e2e.py \
--heldout --all --out docs/release-evidence/llm-primary-20261021/final/heldout-60.json

# factual audit (from a copy of factual-audit/; writes next to itself)
python3 /tmp/audit-run-16000-1/audit.py \
  docs/release-evidence/llm-primary-20261021/final/budget-16000.trial1.responses.jsonl

# preflight (in-process; loads .env, then overrides with production-shaped local values)
uv run --package knicksiq-api python -c "<env loader and preflight.cli.main shown in the log>"
```

The exact preflight invocation is the one-liner that loads `.env`, overrides `DB_URL`,
`REDIS_URL`, `ENVIRONMENT=production`, `REQUIRE_ACTIVE_RELEASE=true`, a 44-character test
`IP_HASH_SECRET`, `CORS_ORIGINS=["https://www.knicksiq.win"]`,
`PUBLIC_WEB_ORIGIN=https://www.knicksiq.win`, `TRUSTED_HOSTS=["api.knicksiq.win"]`,
`OPENROUTER_ALLOWED_MODELS=["deepseek/deepseek-v4.1-flash"]`, a format-valid placeholder
`SENTRY_DSN`, `ANALYSIS_SHADOW_SAMPLE_RATE=0.1`, cutoff 2, `llm_primary`, evidence loop on,
then calls `main(["--json-out", ".../final/preflight.json"])`.

## Artifacts

- `budget-8000.summary.json`, `.rows.jsonl`, `budget-8000.trial{1,2}.responses.jsonl`
- `budget-16000.summary.json`, `.rows.jsonl`, `budget-16000.trial{1,2}.responses.jsonl`
- `budget-8000-drops.summary.json`, `.rows.jsonl`, `.trial1.responses.jsonl`
- `audit-16000-trial{1,2}/` (summary, incorrect, unsupported, missed answers, verdicts)
- `heldout-60.json`, `.scored.jsonl`, `.responses.jsonl`, `heldout-60.audit-summary.md`
- `preflight.json`
- `ab_runner.py` (instrumentation; patches only at runtime)
