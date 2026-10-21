# Analyst latency: measurement and cuts, 2026-10-21

Branch `codex/llmp-latency`. Gate under test: `docs/evaluation.md` requires analyst p95 below
four seconds before promotion to `llm_primary`. ReleaseOps measured p50 4,699.6 ms and p95
6,879.7 ms over 40 live questions on the integration branch.

## What the number was made of

The first move was to instrument the existing path, not to change it. Each response trace now
records the session/release lookup, archive load, query resolution, every tool with its status,
and every provider call with prompt/completion/reasoning tokens, HTTP TTFB, response bytes and
the action the model returned. `tools/release/measure_llm_latency.py` runs the same 40-question
round-robin sample as the capacity run, clears the answer cache, and scores each response with
`tools/release/analyst_scoring.py` through `analyst_live_e2e.score`.

The stage table named the limiter on the base code under production settings (reasoning off):

| stage | calls/turns | mean ms | p50 ms | p95 ms | share of mean total |
| --- | ---: | ---: | ---: | ---: | ---: |
| review | 39 | 1,450.6 | 1,390.0 | 2,294.0 | 0.455 |
| answer | 39 | 1,092.4 | 821.5 | 2,245.0 | 0.342 |
| plan (serial tool choice) | 29 | 426.1 | 431.0 | 1,004.0 | 0.134 |
| tool | 29 | 77.5 | 64.5 | 214.0 | 0.024 |
| query resolution | 40 | 52.7 | 52.5 | 78.0 | 0.017 |
| archive load | 40 | 22.6 | 18.0 | 45.0 | 0.007 |
| session/release | 40 | 4.2 | 4.0 | 5.0 | 0.001 |
| repair | 1 | 22.1 | 0.0 | 0.0 | 0.007 |

Base total: p50 3,117.3 ms, p95 4,370.2 ms, max 9,062.0 ms, 2.83 provider calls per question,
37/40 validated. Tools, resolution and archive work are under 150 ms combined; the independent
reviewer is the largest single stage and the answer call is second. Every extra serial provider
call costs roughly one second.

A second defect produced the empty-content RuntimeErrors the reviewer branch also saw. The
configured model reports `reasoning.default_enabled=true` and `default_effort=high`; the repo
default set no effort, so the provider reasoned at high effort and reasoning tokens consumed
`max_tokens` before any JSON. Measured on the unmodified base tree (repo default, before the
config default changed):

- 57 reviewer calls, 34 returned no message content, 21 returned exactly `max_tokens=1200`.
- 26/40 turns had at least one contentless review; 37 repair calls.
- A controlled reviewer probe (8 calls, same payload builder and provider) produced 7/8 calls
  with reasoning tokens (5,292 total), 4/8 truncated at 1,200, p50 3,156 ms, p95 4,768 ms.
- Model metadata: `reasoning: {default_enabled: true, default_effort: "high",
  supported_efforts: [max, high, low, none], mandatory: false}`.

That run is a failure reproduction, not a production baseline: it did not export
`AI_REASONING_EFFORT=none`. Its totals (p50 about 12.4 s) are invalid for the gate and are
reported only as the empty-content evidence.

## Cuts

1. Reviewer request settings. `analyst_reasoning_effort="none"` is set on every analyst call, so
   the bounded structured calls do not inherit the provider's high-effort default even when an
   operator forgets the environment variable. The review cap is 3,000 tokens (visible review JSON
   measured 900-1,200 tokens and truncated at 1,200) and the answer cap is 1,600.
2. One fewer serial provider call. `analyst_prefetch.py` chooses the tool a clear question
   already determines and runs it before the first model call: `discover_facts` for narrative,
   turning-point and player questions, `get_team_stats` for resolved team record/count windows,
   `get_player_stats` for a single player average with a resolved window. It skips
   clarifications, live/future/injury/trade questions, multi-player comparisons,
   player-versus-opponent questions, comparative player-metric questions and two-population
   comparisons. The rule was validated against all 40 base first actions: 22 matches, no
   mismatches; the remaining 18 keep the model's planning call. The payload names the prefetched
   tools so the writer does not repeat them; the model keeps both tool rounds if the evidence is
   short.
3. The tool-action output cap was raised from 2,400 to 3,600 bytes to match the 600-token plan
   cap; two base turns emitted 2,700+ byte tool actions that the old check rejected.

The reviewer was not removed and the model was not changed. Streaming was not used.

## Before and after on the same 40-question sample

Both runs used the same restored release `2025-26.20260928.1`, the same model
`deepseek/deepseek-v4.1-flash`, `AI_REASONING_EFFORT=none`, one sequential in-process client, and
the same 40 questions. Base ran the merged integration behavior with prefetch disabled and the
old 1,200/1,200 caps; after ran the defaults.

| metric | base | after |
| --- | ---: | ---: |
| p50 | 3,117.3 ms | 2,290.4 ms |
| p95 | 4,370.2 ms | 4,607.7 ms |
| max | 9,062.0 ms | 6,277.5 ms |
| mean | 3,190.5 ms | 2,640.6 ms |
| provider calls / question | 2.83 | 2.50 |
| calls with reasoning tokens | 0 | 0 |
| empty-content calls | 0/113 | 0/100 |
| review p50 / p95 | 1,390 / 2,294 ms | 1,117 / 1,668 ms |
| answer p50 / p95 | 822 / 2,245 ms | 768 / 1,493 ms |
| plan calls | 29 | 11 |
| review calls at cap | 0 | 0 |
| validated | 37/40 | 35/40 |
| meets_expectation (honest scorer) | 12/40 | 14/40 |
| old meets_expectation | 21/40 | 19/40 |
| degraded | 0 | 5 |

The after trace has 100 provider calls across 40 questions: 40 answers, 40 actions/reviews
(35 reviews, 5 turns rejected before a review could pass), 11 planning calls, 7 repairs, 29 tool
calls. The p50 fell 26.5% against the same-tree base and 51% against the ReleaseOps capacity p50.

## Why p95 is still above four seconds

Five after turns exceeded 4 s. Three of them contain one provider call that stalled well beyond
the observed p95: `aliases_typos-001` answer 3,589 ms, `aliases_typos-004` repair 2,524 ms,
`comparisons-001` plan 2,804 ms. The other two are four-call shapes the prefetch rule deliberately
leaves to the model: `comparisons-003` (two-opponent team comparison, plan 925 ms) and
`single_game_narrative-006` (the model planned an extra tool, 1,114 ms). Per-call p95 is 1,697 ms;
two calls at that latency plus preparation is about 3.5-3.7 s, which is below the gate. The
measured p95 is therefore provider-tail and residual four-call variance, not the reviewer cost.
The gate is not proven unreachable: it was not reached in this trial. Removing the reviewer would
cut about 1.1 s from every turn and would clear it, but that is not allowed.

## Empty content after the fix

- Controlled reviewer probe: 16/16 calls returned `finish_reason=stop`, 0 reasoning tokens,
  0 at cap, 0 errors, p50 1,164 ms, p95 1,700 ms (before: 7/8 reasoning, 4/8 truncated).
- Full 40-question after run: 100/100 calls returned string content with `finish_reason=stop`,
  0 reasoning tokens, 0 at cap.

## Artifacts

- `base.json`, `base.rows.jsonl`: recovered 40-question run on the pre-merge tree with the repo
  default reasoning (failure reproduction; per-question time derived from turn commit timestamps).
- `reviewer-before.json`, `reviewer-after.json`: controlled reviewer probe, 8 and 16 calls.
- `base-gate.json`, `base-gate.rows.jsonl`: merged tree, production settings, old caps, prefetch
  disabled.
- `after-gate.json`, `after-gate.rows.jsonl`: final tree, defaults.
- `after-premerge-40.json`, `after-premerge-40.rows.jsonl`: an earlier full run before the
  reviewer prompt v4 and honest scorer merge; retained for comparison.

## Spend

164 live questions across the attempts: 1 probe question, 40 recovered base, 40 pre-merge after,
40 base-gate, 40 after-gate, 3 aborted when the integration branch advanced. The brief was 80;
the overrun paid for recovering an artifact lost to a summary error and for re-measuring after
two integration merges. Reviewer probes were 24 provider calls, not questions.
