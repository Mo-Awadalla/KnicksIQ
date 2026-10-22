# Reasoning experiment: does letting the models think make answers more accurate?

Branch `codex/llmp-w4-thinking`, worktree `~/.local/share/knicksiq/worktrees/w4-thinking`,
base `347b9e9c7cc25ae3cb169d8eda248a46a474272f` of `codex/llmp-integration`. No application
file is edited: the three arms differ only by environment variables, and every artifact here
was produced by `arm_runner.py`, which reuses `w4-bench/bench_runner.py` for the honest score,
the priced ledger and stage latency.

Owner's question: would turning reasoning on make answers more accurate? Numbers in answers
come from backend SQL claims, but thinking could still help tool choice, declines, follow-up
interpretation and repair calls, today's main failure causes.

## 1. Method

**Sample.** 30 fixed questions, 2 trials per arm, 180 live turns. `select_sample.py` picks the
first three ids (file order) of each of the seven scored categories (21) plus the first nine
questions that failed a model stage in w4-bench trial 1 and were not already picked (9). The
ids, categories and reasons are in `sample.json`. The same list, in the same order, ran in all
arms. `follow_ups` is excluded, as in the harness's own sampler.

**Arms.** Only these settings differ; `run.sh` sets them after `/tmp/go.env`.

| Arm | `AI_REASONING_EFFORT` | `ANALYST_REASONING_EFFORT` | answer cap | review cap |
| --- | --- | --- | ---: | ---: |
| A (production today) | `none` | `none` | 1600 | 3000 |
| B | `low` | `low` | 4000 | 6000 |
| C | `medium` | `medium` | 4000 | 6000 |

Env names map one-to-one onto the settings model (`Settings` has no env prefix, extra ignored):
`AI_REASONING_EFFORT` → `ai_reasoning_effort`, `ANALYST_REASONING_EFFORT` →
`analyst_reasoning_effort`, `ANALYST_ANSWER_MAX_TOKENS` → `analyst_answer_max_tokens`,
`ANALYST_REVIEW_MAX_TOKENS` → `analyst_review_max_tokens`. On the wire, Chat Completions
(DeepSeek) takes a top-level `reasoning_effort`; Responses (Luna) takes `reasoning.effort`
(`llm_wire.py`). Both take the adapter's `reasoning_effort`, which the analyst loop overrides
with `analyst_reasoning_effort` for every call.

**Verification first.** A 2-question smoke per arm ran before the full runs and is committed at
`ae29ca8` (`smoke-A/`, `smoke-B/`, `smoke-C/`). Reasoning tokens are actually spent on both
wire protocols in B and C, and no smoke call was truncated:

| Smoke | Calls | Reasoning tokens | Finish reasons | Served = requested |
| --- | ---: | ---: | --- | --- |
| A | 4 | 0 | stop ×4 | yes |
| B | 6 | 774 (chat 365, responses 409) | stop ×6 | yes |
| C | 4 | 670 (chat 230, responses 440) | stop ×4 | yes |

`arm_runner.py` records the adapter's normalized usage, so Responses-API reasoning tokens
(`output_tokens_details.reasoning_tokens`) are visible; the raw-body parser in
`measure_llm_cost.py` cannot see them. Across all measured calls every served model equals the
requested one (456/456): writer `deepseek-v4.1-flash`/`chat`, reviewer `gpt-6-luna`/`responses`.

Each run flushed Redis db 9 once, then ran both trials; every reservation settles (zero open at
the end) and the ledger delta matches actual usage. No HTTP 429 and no transport error occurred.

## 2. Honest score (tools/release/analyst_live_e2e.py scorer)

| Arm | Trial 1 / 30 | Trial 2 / 30 | Total / 60 | Spread | `llm_validated` / 60 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 18 | 17 | **35** | 1 | 36 (60.0%) |
| B | 16 | 17 | **33** | 1 | 33 (55.0%) |
| C | 16 | 10 | **26** | 6 | 22 (36.7%) |

Claim-backed equals the honest score in every arm (35/33/26). Per category (both trials):

| Category | A | B | C |
| --- | ---: | ---: | ---: |
| exact_statistics | 6/6 | 6/6 | 5/6 |
| date_range_last_n | 7/10 | 7/10 | 6/10 |
| comparisons | 2/12 | 2/12 | 1/12 |
| single_game_narrative | 2/10 | 2/10 | 1/10 |
| turning_points | 3/6 | 2/6 | 0/6 |
| aliases_typos | 5/6 | 4/6 | 3/6 |
| unsupported | 10/10 | 10/10 | 10/10 |

## 3. Failure anatomy

| Outcome | A | B | C |
| --- | ---: | ---: | ---: |
| validated | 28 | 28 | 17 |
| validated_declined | 8 | 5 | 5 |
| fallback:review_rejected | 12 | 15 | 7 |
| failed:revise:ValidationError | 8 | 8 | 4 |
| failed:review:TimeoutError | 0 | 2 | 21 |
| failed:revise:TimeoutError | 1 | 0 | 2 |
| failed:orchestrate:RuntimeError | 0 | 2 | 3 |
| failed:orchestrate:ValidationError | 1 | 0 | 0 |
| failed:orchestrate:TimeoutError | 2 | 0 | 1 |

- **`failed:revise:ValidationError` is unchanged by thinking**: 8, 8 and 4. The hypothesis that
  reasoning fixes repair-schema failures is not supported; the 4000-token repair cap fits the
  thinking, and the same malformed repairs come back.
- **Truncation moved to the plan call, not the answer.** No answer call (4000) and no completed
  review call (6000) hit the length limit. Every truncated call was the Action-schema plan call,
  which the app still caps at 600 tokens (`analyst_provider.py`, `schema is Action and not
  loop.tools.claims`): B 2 of 30 plan calls (6.7%), C 7 of 31 (22.6%), A 0 of 29. In B both
  truncated calls returned empty content and failed the turn (`failed:orchestrate:RuntimeError`);
  in C three did, and four returned parseable output. The 600 cap is not reachable from
  `ANALYST_ANSWER_MAX_TOKENS`, so the arm env could not protect it without a code change.
- **The 30 s analyst deadline becomes the dominant failure at medium.** Deadline-cancelled
  provider calls: A 1, B 2, C 24 (21 of them reviews). C's review stage p95 is 20.0 s on its own.
- Empty model outputs: 0 in every arm. Truncated outputs: 0 / 2 / 7 (all plan calls).
- Review rejections rose in B (15) before the deadline cancellations displaced them in C (7).
- The pre-run smoke was clean in all arms; the first truncation appeared in B's full run, so no
  cap was tuned and no arm was rerun. C ran as scheduled because medium is a different setting,
  and its truncation rate (7/31) and 21 review deadline cancels are reported as the answer, not
  worked around.

## 4. Unsupported declines

Five unanswerable questions per trial (10 turns). Explicit declines (`validated_declined`):
A 6/10, B 3/10, C 5/10. The honest scorer still gives every arm 10/10 in the category because a
failed turn's fallback text ("I can't answer that: verified archive facts are unavailable…") is
read as a decline. That number is therefore not a model decision; the explicit count is.
B also declined two answerable questions (`turning_points-002`, `comparisons-010`), which costs
honest score.

## 5. Wrong numbers (full SQL factual audit)

Run with the improved audit from the `codex/llmp-integration` worktree at head `1647a51` (that
path last changed in `5d372fe`), one version for all arms:
`AUDIT_DIR=…/integration/docs/release-evidence/llm-primary-20261021/factual-audit ./audit.sh`.

| Arm | Responses | Atoms found | Verified | Wrong | Unverified | Coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 60 | 467 | 349 | 5 | 113 | 75.80% |
| B | 60 | 501 | 314 | 4 | 183 | 63.47% |
| C | 60 | 568 | 421 | 0 | 147 | 74.12% |

Nine atoms are flagged wrong. Read with the sentence's stated scope, every one is a binder
error, not a wrong value:

- `comparisons-010` (A trial 1, B trial 2): 121.75 / 53 / 29 / 106.76 bound to all-phase; SQL
  `season_type='regular'` gives 53 wins at 121.75 for and 29 losses at 106.76, and 53+29=82
  states the regular season in the answer.
- `comparisons-002` (A trial 2): the 74 is Brunson's appearances in a sentence that says so;
  the audit bound it to Towns (75).
- `single_game_narrative-001` (A trial 1, B trial 2): an 18-point deficit typed as a comeback,
  and a 12-0 run typed as a team record.
- `turning_points-001` (B trial 2): the audit reports "no matching run" for the 17-0; SQL over
  `game_events` game 2 (2025-10-24 vs BOS) shows NYK 33→50 with BOS stuck on 36 from Q2 07:48
  to 03:36, i.e. the stated Q2 07:29–03:49 span is correct.

C's zero wrong atoms therefore does not show better grounding: C delivered 17 validated answers
against A's 28 and wrote more unverified text (147 unverified atoms). No arm produced a
demonstrable wrong number in this sample.

## 6. Latency, reasoning tokens and cost

Latency is wall time around `POST /analysis/query`, nearest-rank percentiles. Cost is the
monthly ledger delta (authoritative), reconciled per question.

| Metric | A | B | C |
| --- | ---: | ---: | ---: |
| p50 ms (trial 1 / trial 2) | 7,162.7 / 6,809.2 | 10,858.6 / 13,665.8 | 20,202.3 / 19,067.4 |
| **p50 ms, both trials** | **7,014.4** | **12,007.2** | **19,303.4** |
| **p95 ms, both trials** | **14,647.1** | **23,564.8** | **27,631.0** |
| Reasoning tokens / question | 0.0 | 427.3 | 697.6 |
| — DeepSeek (Chat) / question | 0.0 | 318.0 | 547.9 |
| — Luna (Responses) / question | 0.0 | 109.3 | 149.7 |
| Ledger, 60 questions | $0.164593 | $0.1925152 | $0.4126013 |
| Cost / question | $0.002743217 | $0.003208587 | $0.006876688 |
| Monthly capacity at $2 | 729 | 623 | 290 |
| Mean provider calls / question | 2.62 | 2.53 | 2.45 |
| Provider calls | 157 | 152 | 147 |

Stage medians (p50 ms) show where the time goes: plan 1,555 → 2,930 → 3,247; answer
2,418 → 3,685 → 5,167; review 4,225 → 6,608 → 12,661; repair 2,332 → 3,102 → 4,283.

C's ledger includes $0.24 of flat $0.01 reservations settled for the 24 calls cancelled at the
deadline; priced completed calls total $0.172601 ($0.002877/question, 695/month). Those
cancellations are caused by reasoning, so the ledger cost is the honest production cost under
the $2 cutoff. For the same reason five turns (2 in B, 3 in C) do not reconcile in the per-call
estimate: their billed-but-empty replies were priced in the ledger and charged at the
reservation in the per-call estimate. The ledger is authoritative and reconciles in total.

Wall time: A 496.7 s, B 797.5 s, C 1,153.8 s. Calls spent: 456 measured + 14 smoke = 470.

## 7. Recommendation

**Keep reasoning off (arm A).** Quality comes first, then latency, then cost:

1. **Honest score.** A 35/60, B 33/60, C 26/60. The A–B gap is 2 answers (3.3 points), inside
   the arms' own trial spread (1 per trial, so the difference is one question per trial on
   average); it is not a demonstrated accuracy loss on its own. C is 9 answers (15 points)
   behind with a spread of 6, so C is clearly worse.
2. **Wrong numbers.** No arm produced a demonstrable wrong number; the audit's 5/4/0 flags are
   binder errors. So the second criterion does not separate A from B, and C's zero is bought by
   answering less.
3. **Latency.** B roughly doubles p50 (+71%) and raises p95 by 61%; C nearly triples p50 and
   sits at 27.6 s p95 against a 30 s deadline, which is why it loses 21 reviews to timeouts.
4. **Cost.** B +17% per question and 623 questions/month at $2 against A's 729; C +151% and 290.

The mechanism is not subtle: thinking did not reduce the repair-schema failures that dominate
today's failures (8 → 8 → 4, with fewer repair attempts in C because turns died earlier), it
added a new failure at the 600-token plan call that the arm's env cannot raise, and at medium
it pushes the reviewer into the analyst deadline. Turning reasoning on would need at least the
plan-call cap and the deadline revisited first; even then, B's quality is not better than A's
inside this sample, so the config change buys nothing measurable.

## 8. Reproduce

```sh
cd docs/release-evidence/llm-primary-20261021/w4-thinking
./run.sh A smoke && ./run.sh B smoke && ./run.sh C smoke   # 2 questions each
./run.sh A full && ./run.sh B full && ./run.sh C full      # 30 questions, 2 trials each
AUDIT_DIR=$HOME/.local/share/knicksiq/worktrees/integration/docs/release-evidence/\
llm-primary-20261021/factual-audit ./audit.sh
python3 summarize_arms.py
```

Artifacts per arm under `arm-X/`: `trial{1,2}.json`, `trial{1,2}.scored.jsonl`,
`trial{1,2}.responses.jsonl`, `calls_normalized.jsonl` (one row per provider call with stage,
model, protocol, cap, finish reason, reasoning tokens and priced cost), `ledger.jsonl`,
`metrics.json` (bench metrics plus `arm_extra` and the settings snapshot), `audit/trial{1,2}/`.
Plus `sample.json`, `smoke-*/`, `summary.json`, `arm-{A,B,C}.log`, and the scripts.

Observed results: honest 35 / 33 / 26 of 60; zero demonstrated wrong numbers; unsupported
explicit declines 6 / 3 / 5 of 10; p95 14.6 / 23.6 / 27.6 s; 729 / 623 / 290 questions per month
at $2. Verdict: **recommendation to keep reasoning off**; the A-versus-B quality difference is
inside the spread, the latency, cost and new failure modes are not.

## Open risks

- 30 questions is a small sample: one answer is 1.7 points per trial. A and B are separated by
  one answer per trial; only C is separated by more than its spread.
- The honest scorer credits a failed turn's canned decline text on unanswerable questions, so
  the unsupported category reads 10/10 everywhere. The explicit decline count is the usable
  signal.
- The audit still mis-binds some scopes and subjects (section 5), so its wrong count is an
  upper bound and its `verified` count is not a full pass.
- The plan-call 600-token cap and the 30 s deadline are application constants; this experiment
  could not change them, and they are the two reasons thinking fails in production-like use.
