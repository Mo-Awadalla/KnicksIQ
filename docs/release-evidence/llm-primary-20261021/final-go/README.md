# Final Go measurement: 70-question benchmark, follow-ups and full SQL audit

Frozen code: `51f184a` on `codex/llmp-integration` ("Keep reasoning off; freeze for the final
runs"). Worktree `~/.local/share/knicksiq/worktrees/final2`, branch `codex/llmp-final2`, Redis
db 10 flushed once before the first run. No file under `apps/` or `packages/` was edited.

Host: OpenCode Go (`https://opencode.ai/inference/go/openai/v1`). Writer
`deepseek-v4.1-flash` over Chat Completions, reviewer `gpt-6-luna` over the Responses API,
`AI_REASONING_EFFORT=none` (the default), `ANALYSIS_ANSWER_MODE=llm_primary`,
`ANALYST_EVIDENCE_LOOP_ENABLED=true`, `RAG_QDRANT_ENABLED=false`, `ANALYST_INPUT_TOKENS` at the
16,000 default, monthly cutoff $2. The two live runs made 684 provider calls
(370 benchmark + 314 follow-up), with 0 transport errors, 0 `MissingSessionID` and no HTTP 429.

The 70-question sample is exactly `analyst_live_e2e.py --per-category 10`: the first 10
questions of each of the 7 categories, 70 per trial. The benchmark used the w4-bench runner
(`../w4-bench/bench_runner.py`) unchanged, because it records the priced ledger and per-call
detail the plain harness does not; it calls the harness's own `classify`, `score` and
`summarize`. The follow-up run is `tools/release/followup_bench.py --trials 2` on the committed
27 sessions. Wall time: benchmark 1,486.71 s, follow-up 1,121.49 s.

## 1. Honest score per category, per trial, spread

`meets_expectation` from `analyst_scoring.py` through the harness. Claim-backed equals the
honest score in both trials (42 and 40).

| Category | Trial 1 / 10 | Trial 2 / 10 | Spread |
| --- | ---: | ---: | ---: |
| exact_statistics | 10 | 10 | 0 |
| date_range_last_n | 7 | 7 | 0 |
| aliases_typos | 8 | 4 | 4 |
| comparisons | 3 | 5 | 2 |
| unsupported | 8 | 8 | 0 |
| turning_points | 4 | 4 | 0 |
| single_game_narrative | 2 | 2 | 0 |
| **Total / 70** | **42** | **40** | **2** |

Honest total 82/140 (58.6%): trial 1 42/70 (60.0%), trial 2 40/70 (57.1%), spread 2.
Outcomes per trial:

| Outcome | Trial 1 | Trial 2 |
| --- | ---: | ---: |
| validated | 39 | 35 |
| validated_declined | 6 | 6 |
| fallback:review_rejected | 22 | 25 |
| fallback:other | 1 | 1 |
| failed:orchestrate:TimeoutError | 1 | 3 |
| failed:review:TimeoutError | 1 | 0 |

Five turns failed a model stage (4 orchestrate timeouts, 1 review timeout), down from 28 at
`536d12e`; repair calls fell accordingly (74 vs 79). Review rejections rose to 47/140 (33.6%)
from 31/140 (22.1%). Validated responses are 74 (39+35).

## 2. Unsupported category and explicit declines

The 10-question sample contains 8 unanswerable and 2 answerable questions. Every one of the 8
unanswerable questions was explicitly declined in both trials: **8/8 and 8/8, 16/16**. All 16
carried `refused=true`; the stricter `outcome=validated_declined` count is 4 in trial 1 and 5 in
trial 2, the rest being declines delivered through a fallback path. The two answerable questions
(`unsupported-009`, `-010`) failed in both trials, so the category's honest score is 8/10 in each
trial (16/20). Declining those two would be wrong: they are answerable.

## 3. Follow-up benchmark (27 sessions, 64 turns per trial, 128 turns)

| Metric | Trial 1 | Trial 2 | Both | Spread |
| --- | ---: | ---: | ---: | ---: |
| Turns pass | 58/64 | 58/64 | 116/128 (90.6%) | 0 |
| Session runs pass | 21/27 | 21/27 | 42/54 (77.8%) | 0 |
| Model path (`llm_validated=true`) | 60/64 | 61/64 | 121/128 (94.5%) | 1 |
| Fallback / degraded | 4 | 3 | 7/128 (5.5%) | 1 |
| Scope-clean session runs | 27/27 | 27/27 | 54/54 | 0 |

Session spread: 19 sessions pass both trials, 4 pass exactly one, 4 pass neither. The 12
failing turns are 7 `pipeline:degraded`, 3 `answer:value` and 2 `answer:declined`; no session
lost scope integrity. Model-path share is 94.5% of turns; every routed call carried the expected
model and wire protocol: 149 orchestrate + 33 revise calls to `deepseek-v4.1-flash`/`chat`,
132 review calls to `gpt-6-luna`/`responses`, 0 `served_model` mismatches (prepare and tool
entries are local stages).

## 4. Full SQL audit, both 70-question trials

`factual-audit/audit.py` on `bench/trial{1,2}.responses.jsonl`; raw output under `audit/`.

| Metric | Trial 1 | Trial 2 | Both |
| --- | ---: | ---: | ---: |
| responses | 70 | 70 | 140 |
| numeric atoms found | 635 | 673 | 1,308 |
| checked (verified + wrong) | 424 (66.77%) | 487 (72.36%) | 911 (69.65%) |
| verified | 418 | 482 | 900 |
| **flagged wrong** | **6** | **5** | **11** |
| unverified | 211 | 186 | 397 |

Every flagged atom was recomputed from the raw restore tables with SQL under the scope its own
sentence states (`audit/flag-verdicts.md`, one query per atom). **11 BINDING, 0 REAL.** The
audit's usual failure modes recur: it bound Brunson's 74 appearances to Towns; a player's
8-point game to team points; an aggregate +12 margin to a per-game margin; a loss count to wins;
a deficit to a "comeback"; a lead snapshot to a run; a NYK run to BOS/CHA; and it expected a
20-0 run to end at Q1 01:01 instead of Q1 05:53. It also verified the identical
`aliases_typos-005` run claim in trial 2 that it flagged in trial 1, so its binding is not
stable between identical sentences.

**Real wrong numbers: none.** The list is empty. That is not a clean bill of health for the
whole set: 397 atoms (30.4%) remain unverified, so "zero wrong numbers" cannot be certified
from this audit.

## 5. Latency per question and per stage

Latency is wall time around `POST /analysis/query`; per-stage values are the trace's own
`latency_ms` per occurrence (nearest-rank p50/p95), with `prepare_total` excluded so nothing is
counted twice. Shares are of the summed stage time over both trials.

| Trial | p50 ms | p95 ms | mean ms |
| --- | ---: | ---: | ---: |
| 1 | 8,818.5 | 18,767.9 | 10,296.2 |
| 2 | 9,444.5 | 20,203.9 | 10,800.7 |
| **Both** | **9,260.7** | **19,832.9** | **10,548.5** |

| Stage | Calls | p50 ms | p95 ms | Mean ms | Share |
| --- | ---: | ---: | ---: | ---: | ---: |
| review | 113 | 5,459 | 11,128 | 6,027.3 | 46.5% |
| answer | 139 | 3,073 | 5,770 | 3,474.2 | 32.9% |
| repair | 74 | 2,492 | 4,232 | 2,664.7 | 13.5% |
| plan | 44 | 1,658 | 2,208 | 1,744.6 | 5.2% |
| tool | 121 | 77 | 597 | 132.8 | 1.1% |
| query_resolution | 138 | 56 | 75 | 55.3 | 0.5% |
| archive_records | 138 | 21 | 54 | 26.7 | 0.3% |
| session_and_release | 138 | 4 | 7 | 4.6 | 0.0% |

The p95 target (< 4 s) is not met. The tail is dominated by review (p95 11.1 s) and the three
20-25 s timeout turns; the median question is 9.3 s.

## 6. Cost and capacity at $2

Cost is the monthly ledger delta; every question is reconciled against the sum of its priced
provider calls plus its open-reservation change.

| Metric | Value |
| --- | ---: |
| ledger delta, 140 questions | $0.3718882 |
| sum of per-call priced costs | $0.3718882 |
| settled total | $0.3718882 |
| open-reservation delta | $0 |
| reconciled (`per-call + open delta`) | $0.3718882 |
| questions reconciled | 140/140, no residual |
| trial 1 ledger | $0.1861849 ($0.002659784/q) |
| trial 2 ledger | $0.1857033 ($0.002652904/q) |
| mean per question | $0.002656344 |
| p50 / p95 per question | $0.0022291 / $0.0048155 |
| by stage (6 dp) | orchestrate $0.228165, repair $0.080139, review $0.063584 |
| **monthly capacity at $2** | **752 questions** |

Calls: 370 total, 2.64 per question (2.73 trial 1, 2.56 trial 2), p50 2, p95 4, max 6; 183
orchestrate, 113 review, 74 revise. 257 calls went to `deepseek-v4.1-flash` (chat), 113 to
`gpt-6-luna` (responses); 3 timed-out calls returned no `served_model`/protocol metadata. No
call returned a transport error, and no call reported a non-zero reasoning-token count (230
reported 0, 140 omitted the field).

## 7. Done predicate, item by item

1. **60/70 honest: NOT VERIFIED.** 42/70 and 40/70 (82/140), spread 2. Best trial 42.
2. **≥ 80% fresh held-out: NOT VERIFIED.** Not measured here; the held-out sets were left
   untouched as the wave-4 rule requires. No held-out number is claimed.
3. **Zero wrong numbers by the full SQL audit: NOT VERIFIED.** The audit flags 11 atoms
   (6 + 5). Independent SQL shows all 11 are BINDING, so 0 real wrong numbers were found, but
   coverage is 66.77% / 72.36% and 397 atoms are unverified; zero wrong cannot be certified.
4. **Unsupported 10/10 declined: NOT VERIFIED as written.** 8/8 unanswerable questions were
   explicitly declined in each trial (16/16). The sample's other 2 unsupported questions are
   answerable and failed; declining them would be wrong.
5. **Suites green: VERIFIED.** `env -i HOME=$HOME PATH=$PATH TEST_MODE=true uv run pytest apps
   packages tools/report_audit` → 439 passed in 33.04 s. `ruff check apps packages migrations`
   and `ruff format --check apps packages migrations` → clean; `pyright apps packages
   migrations` → 0 errors. (At the frozen SHA, `tools/release/followup_scope_repros.py` has one
   pre-existing unused import and one format diff; it is outside the gate's scope and was not
   edited.)
6. **Latency/cost measured (p95 target < 4 s): measurement VERIFIED; target NOT VERIFIED.**
   140/140 ledger reconciliation, 752 questions/month at $2; p95 is 19,832.9 ms, p50 9,260.7 ms.

## 8. Comparison with w4-bench (`536d12e`)

Both runs used the same host and the same reviewer: OpenCode Go, writer
`deepseek-v4.1-flash` over Chat Completions, reviewer `gpt-6-luna` over the Responses API,
reasoning `none`, 16,000 input tokens, $2 cutoff, and the same 70-question sample. The only
intended difference is the code: `536d12e` (w4-bench) versus `51f184a` (this run). Provider-side
day-to-day latency/cost drift is not controlled, so small latency and cost deltas carry that
caveat; the score and routing deltas are code.

| Metric | w4-bench `536d12e` | final-go `51f184a` | Delta |
| --- | ---: | ---: | ---: |
| honest / 70, trial 1 | 36 | 42 | +6 |
| honest / 70, trial 2 | 35 | 40 | +5 |
| honest / 140 | 71 | 82 | +11 (+7.9 pts of 140) |
| spread | 1 | 2 | +1 |
| failed model stages / 140 | 28 | 5 | -23 |
| review rejections / 140 | 31 | 47 | +16 |
| provider calls | 354 | 370 | +16 |
| calls per question | 2.53 | 2.64 | +0.11 |
| audit flagged wrong | 36 | 11 | -25 |
| audit unverified atoms | 453 | 397 | -56 |
| audit verified atoms | 752 | 900 | +148 |
| unsupported declines (unanswerable) | 7/8 + 7/8 | 8/8 + 8/8 | +1 each |
| follow-up turns pass | 90/128 | 116/128 | +26 |
| follow-up session runs pass | 24/54 | 42/54 | +18 |
| follow-up model path | 106/128 | 121/128 | +15 |
| follow-up scope-clean runs | 51/54 | 54/54 | +3 |
| p50 ms | 7,453.1 | 9,260.7 | +1,807.6 (+24.3%) |
| p95 ms | 14,957.7 | 19,832.9 | +4,875.2 (+32.6%) |
| mean ms | 8,011.9 | 10,548.5 | +2,536.6 (+31.7%) |
| ledger, 140 questions | $0.3484581 | $0.3718882 | +$0.0234301 (+6.7%) |
| mean cost / question | $0.002488986 | $0.002656344 | +6.7% |
| monthly capacity at $2 | 803 | 752 | -51 (-6.3%) |

The code at `51f184a` buys 11 more honest answers and removes 23 failed model stages, at the
cost of more review rejections, a 24-33% slower tail and 6.7% more cost per question. Follow-ups
improve on every measured axis, including 54/54 scope-clean session runs.

## Artifacts and reproduce

- `bench/metrics.json`, `trial{1,2}.json`, `trial{1,2}.scored.jsonl`,
  `trial{1,2}.responses.jsonl`, `calls.jsonl`, `ledger.jsonl`, `run.log`
- `audit/trial{1,2}/{rows.jsonl,summary.md,diff.md}`, `audit/flag-verdicts.md`
- `followup/followup_sessions.json` (raw harness output; its `base` field is the harness's
  static default `5b585e6`, not the measured SHA), `followup/summary.json`, `followup/run.log`
- `run.sh` reproduces all three stages; `MANIFEST.md` lists SHA provenance.

```sh
. /tmp/go.env
export REDIS_URL=redis://localhost:56500/10
docker exec kiq-integrate-redis-1 redis-cli -n 10 flushdb
uv run --package knicksiq-api python docs/release-evidence/llm-primary-20261021/w4-bench/bench_runner.py \
  --trials 2 --per-category 10 --out-dir docs/release-evidence/llm-primary-20261021/final-go/bench
uv run --package knicksiq-api python tools/release/followup_bench.py --trials 2 \
  --out docs/release-evidence/llm-primary-20261021/final-go/followup/followup_sessions.json
for t in 1 2; do uv run --package knicksiq-api python \
  docs/release-evidence/llm-primary-20261021/factual-audit/audit.py \
  docs/release-evidence/llm-primary-20261021/final-go/bench/trial$t.responses.jsonl \
  --out docs/release-evidence/llm-primary-20261021/final-go/audit/trial$t \
  --label "final-go trial $t"; done
```

## Open risks

- The audit's 397 unverified atoms are not passes. A zero-wrong claim needs either better
  binding in the audit or a different scope.
- Three 20-25 s timeout turns inflate p95; p95 also includes the 47 review rejections, whose
  reviews take a median 5.5 s.
- `aliases_typos` is the least stable category (8 vs 4). It is also where the audit's binding
  errors concentrate.
- The follow-up run used Redis db 10 after the benchmark without a second flush; each session
  uses fresh turn ids and revision 0, and all 27 sessions committed consecutive revisions, so
  there is no evidence of cross-run state leakage.
