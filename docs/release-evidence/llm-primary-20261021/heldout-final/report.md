# Held-out v2 final measurement

**Held-out gate: NOT VERIFIED.** The honest scorer passed 41/80 questions (51.25%, Wilson 95% CI 40.49–61.89%), below the required 64/80. Full per-category intervals are below and in `metrics.json`. This is one live trial only; no answers were used to tune or change the candidate, and no live run was repeated.

- Frozen code SHA: `51f184a23645f1d43f930a520a1cc053397a315b` (`Keep reasoning off; freeze for the final runs`).
- Branch: `codex/llmp-w4-heldout-final`.
- Main-question run commit: `b91982d8b638107deaf80df564aa467aef399371`.
- Follow-up run commit (includes the required adapter): `10b3636ab7f90f82d28c2fce9da94e7a27d7085e`.
- Held-out source: `codex/llmp-w3-heldout2` at `e3128fe`.
- Restored release: `2025-26.20260928.1`; Redis db 11 was flushed once before the runs.
- No HTTP 429/account error or pre-answer harness crash occurred; neither run was restarted.

## Set validation and execution

The held-out directory and its evidence README were checked out from `e3128fe`. The generated-set gate passed:

```sh
. /tmp/go.env
DB_URL="$DB_URL" uv run --package knicksiq-api python -m app.evaluation.heldout_v2.build --check
# held-out v2 files match the generator
```

The generator and an independent digest both yielded `question_order_sha256 = 897c693f9c978cfe2f68a05136cda75d4d74e37c3640bd352c0196f76d3ed9bd`.

Live configuration came from `. /tmp/go.env`: reasoning `none`, writer `deepseek-v4.1-flash` via chat, reviewer `gpt-6-luna` via Responses API; review traces showed `served_model=gpt-6-luna` and `protocol=responses`. In-process requests used `http://test` and the harness's raised public-chat limits.

Main run, executed once:

```sh
. /tmp/go.env
export REDIS_URL=redis://localhost:56500/11
uv run --package knicksiq-api python tools/release/analyst_live_e2e.py \
  --questions apps/api/app/evaluation/heldout_v2/questions.jsonl --all \
  --out docs/release-evidence/llm-primary-20261021/heldout-final/main.json
```

Follow-up run, executed once:

```sh
. /tmp/go.env
export REDIS_URL=redis://localhost:56500/11
uv run --package knicksiq-api python tools/release/heldout_followup_bench.py \
  --out docs/release-evidence/llm-primary-20261021/heldout-final/followups.json
```

The stock `followup_bench.py` accepts a `--sessions` path, but its loader requires a structured `turn.expect.kind` on every turn. The held-out v2 rows instead contain generator-computed `required_facts`, `required_entities`, `required_phrases`, and `filters.game_id`. `tools/release/heldout_followup_bench.py` is the separate-commit thin adapter: it drives two live turns with session token/revision and actual turn-1 history, scores each answer with the same `analyst_scoring.score_response`, calls the same `followup_oracle.scoped`/`compare_scope` and `followup_rescore.classify`, and takes the held-out facts/expected game directly from the committed file. It introduces no new expected-value labels.

Full SQL audit, executed once on the 80 response rows:

```sh
python3 docs/release-evidence/llm-primary-20261021/factual-audit/audit.py \
  docs/release-evidence/llm-primary-20261021/heldout-final/main.responses.jsonl \
  --out docs/release-evidence/llm-primary-20261021/heldout-final/audit-main \
  --label "held-out v2 main 51f184a"
```

Audit output: 80 responses, 393 numeric atoms, 209 verified, 33 initially flagged wrong, 151 unverified. All 33 flags were individually checked against raw-table SQL and labelled **BINDING**, 0 **REAL**; evidence and SQL are in `audit-flags.md`. Unverified atoms are not passes. Thus the audit found **0 confirmed real wrong numbers among its flags**, not 0 unresolved numeric claims.

## Honest score

| Category | Pass | Total | Score | Wilson 95% CI |
| --- | ---: | ---: | ---: | ---: |
| aliases_typos | 5 | 11 | 45.5% | 21.3–72.0% |
| comparisons | 2 | 11 | 18.2% | 5.1–47.7% |
| date_range_last_n | 7 | 12 | 58.3% | 32.0–80.7% |
| exact_statistics | 6 | 12 | 50.0% | 25.4–74.6% |
| single_game_narrative | 8 | 11 | 72.7% | 43.4–90.3% |
| turning_points | 2 | 11 | 18.2% | 5.1–47.7% |
| unsupported | 11 | 12 | 91.7% | 64.6–98.5% |
| **Overall** | **41** | **80** | **51.3%** | **40.5–61.9%** |

Unsupported requests were honestly declined on 11/12 cases. `heldout2-unsupported-008` failed the honest scorer because the decline contains an unbacked number (`1999`).

## Follow-ups

One trial: 9/20 turns passed (turn 1: 9/10; turn 2: 0/10); 0/10 sessions passed. All 10 sessions maintained token/revision integrity and all HTTP 200 turns settled, but every scored second turn missed its required answer/scope; several turn-2 responses fell back to season-wide values or declined. The complete transcript, honest checks, state scopes, and routing evidence are in `followups.json`.

## Latency and cost

Latency values are single-run distributions across responses/turns, not multi-trial estimates. Main per-question trace latency is `prepare_total` plus non-prepare stage latencies (excluding outer app/network overhead): p50 **10,611 ms**, p95 **16,118 ms**, mean 10,740 ms, max 18,768 ms. Stage p50/p95: tool 71/154 ms; orchestrate 2,569/4,437 ms; review 4,947/8,968 ms; revise 2,494/4,118 ms. Main live run wall time was 873.88 s. The p95 latency target of 4 s was not met.

Measured main-run token cost, using the configured price table:

| Model / protocol | Calls | Prompt tokens | Completion tokens | Cost |
| --- | ---: | ---: | ---: | ---: |
| deepseek-v4.1-flash / chat | 164 | 498,592 | 37,353 | $0.194401 |
| gpt-6-luna / responses | 80 | 190,420 | 31,240 | $0.034662 |
| **Main run** | **244** | **689,012** | **68,593** | **$0.229063** |

The follow-up run's recorded trace latency was p50 **8,627 ms** / p95 **23,219 ms** per turn and p50 **22,802 ms** / p95 **31,733 ms** per two-turn session; follow-up wall time was 226.03 s. Its adapter retained model/protocol/latency but not prompt/completion token counts, so its cost cannot be recovered from the saved artifact. No second run was made to recover it. `metrics.json` contains machine-readable results and this limitation.

## Backend gate

Required clean-environment command:

```sh
env -i HOME=$HOME PATH=$PATH TEST_MODE=true uv run pytest apps packages tools/report_audit
```

Result: **439 passed in 32.72 s**.

## Artifacts

- `main.json`, `main.scored.jsonl`, `main.responses.jsonl`: honest main score and one raw response per held-out question; JSONL file-level frozen SHA/content hashes are in the `.meta.json` sidecars.
- `followups.json`: all ten live sessions and 20 scored turns.
- `audit-main/`: full SQL audit output; `audit-flags.md`: every wrong flag's REAL/BINDING decision and recomputation SQL. `audit-main/rows.meta.json` records the JSONL SHA.
- `metrics.json`, `artifact-manifest.json`: machine-readable results and frozen-SHA/content-hash provenance.

Held-out `>= 80%`: **NOT VERIFIED** (41/80, 51.25%).
