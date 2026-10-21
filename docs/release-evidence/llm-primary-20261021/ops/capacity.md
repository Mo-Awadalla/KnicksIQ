# llm_primary capacity at the $2 monthly cutoff

Measured 2026-10-21 with `tools/release/measure_llm_capacity.py` against the restored
`2025-26.20260928.1` release (101 games), the real OpenRouter provider, model
`deepseek/deepseek-v4.1-flash`, and `ANALYSIS_ANSWER_MODE=llm_primary`. Qdrant was disabled.
Artifacts: `capacity.json` (aggregates), `capacity.rows.jsonl` (one row per question).

## Method

- 40 questions, exactly the run budget, selected round-robin from
  `apps/api/app/evaluation/questions.jsonl` across seven categories: exact_statistics,
  date_range_last_n, aliases_typos, unsupported, turning_points, comparisons,
  single_game_narrative. Five or six per category.
- Each question went through the in-process FastAPI app with a fresh 16+ character `turn_id`,
  one at a time, no concurrency. This is the same route and evidence loop as production.
- `charged_usd` per question is the Redis `ai-budget:2026-10` delta measured immediately before
  and after the request. That delta is what `reserve()` and `settle()` enforce, so it is the
  authoritative cost for the cutoff. The provider's reported `usage.cost` is recorded beside it
  as a cross-check; both agreed to eight decimal places in total.
- `tokens` is the provider-reported total across every model call in the turn. `calls` counts
  adapter invocations that reached the provider.
- Latency is wall clock around the HTTP request, including all model calls and fallback work.
  p50 is the median; p95 is nearest-rank, which for 40 samples is the second-highest value.
- The test cutoff was $0.30. The production cutoff is $2.00. Ledger start was $0.01 (a prior
  failed-call reservation), end $0.04624128, so the run's isolated delta is $0.03624128.
- Rate-limit environment variables were raised for the measurement. They are not deployment
  settings; production keeps its defaults.

## Totals

| Metric | Value |
| --- | --- |
| Questions attempted | 40 |
| HTTP 200 / non-200 | 40 / 0 |
| Model-validated answers | 36 |
| Degraded to deterministic facts | 4 |
| Provider calls | 120 |
| Calls per question (mean) | 3.00 |
| Tokens total | 231,195 |
| Tokens per question (mean) | 5,779.9 |
| Charged cost total | $0.03624128 |
| Charged cost per question (mean) | $0.00090603 |
| Charged cost per question (p50) | $0.00089932 |
| Charged cost per question (p95) | $0.00134087 |
| Reported cost total | $0.03624127 |
| Latency p50 | 4,699.6 ms |
| Latency p95 | 6,879.7 ms |
| Latency max | 10,058.5 ms |

At the mean, $2 buys **2,207 questions** per month ($0.906 per 1,000). At p50 it buys 2,223; at
p95 it buys 1,491. The spread is real: the cheapest question cost $0.00030628 and the most
expensive $0.00145040, a 4.7x range. The four degraded turns still paid full provider cost.

## Per-category

| Category | Questions | Validated | Calls | Mean cost | p50 latency |
| --- | --- | --- | --- | --- | --- |
| exact_statistics | 6 | 5 | 18 | $0.00076583 | 3,815.8 ms |
| date_range_last_n | 6 | 6 | 17 | $0.00105155 | 4,990.0 ms |
| aliases_typos | 5 | 5 | 16 | $0.00086758 | 4,253.4 ms |
| unsupported | 5 | 5 | 10 | $0.00055915 | 3,140.3 ms |
| turning_points | 6 | 6 | 15 | $0.00087894 | 4,173.0 ms |
| comparisons | 6 | 5 | 21 | $0.00098292 | 5,412.8 ms |
| single_game_narrative | 6 | 4 | 23 | $0.00117204 | 6,075.4 ms |

Unsupported questions are cheapest because they usually stop after two calls. Single-game
narrative is the most expensive and slowest because it spends the most tool and review calls.

## Per-question measurements

| Question | Category | Calls | Tokens | Charged USD | Latency ms | Validated |
| --- | --- | --- | --- | --- | --- | --- |
| exact_statistics-001 | exact_statistics | 3 | 5937 | 0.00093127 | 5525 | True |
| date_range_last_n-001 | date_range_last_n | 3 | 6774 | 0.00116577 | 4796 | True |
| comparisons-001 | comparisons | 4 | 8432 | 0.00106344 | 6096 | True |
| single_game_narrative-001 | single_game_narrative | 3 | 6505 | 0.00109166 | 5043 | True |
| turning_points-001 | turning_points | 3 | 6109 | 0.00088252 | 4592 | True |
| aliases_typos-001 | aliases_typos | 3 | 6352 | 0.00094786 | 4766 | True |
| unsupported-001 | unsupported | 2 | 3202 | 0.00054382 | 4725 | True |
| exact_statistics-002 | exact_statistics | 3 | 5645 | 0.00082384 | 4075 | True |
| date_range_last_n-002 | date_range_last_n | 3 | 6466 | 0.00127739 | 5184 | True |
| comparisons-002 | comparisons | 3 | 6120 | 0.00092879 | 4675 | False |
| single_game_narrative-002 | single_game_narrative | 4 | 7259 | 0.00124274 | 6880 | False |
| turning_points-002 | turning_points | 2 | 3396 | 0.00064403 | 3020 | True |
| aliases_typos-002 | aliases_typos | 3 | 5905 | 0.00081010 | 4112 | True |
| unsupported-002 | unsupported | 2 | 3521 | 0.00058892 | 2986 | True |
| exact_statistics-003 | exact_statistics | 3 | 5506 | 0.00082900 | 4148 | True |
| date_range_last_n-003 | date_range_last_n | 3 | 5814 | 0.00142919 | 2912 | True |
| comparisons-003 | comparisons | 4 | 7979 | 0.00123866 | 5428 | True |
| single_game_narrative-003 | single_game_narrative | 4 | 6170 | 0.00098821 | 5271 | True |
| turning_points-003 | turning_points | 3 | 6560 | 0.00119154 | 5676 | True |
| aliases_typos-003 | aliases_typos | 4 | 6281 | 0.00082480 | 4253 | True |
| unsupported-003 | unsupported | 2 | 3300 | 0.00059798 | 3140 | True |
| exact_statistics-004 | exact_statistics | 3 | 6029 | 0.00052049 | 3207 | False |
| date_range_last_n-004 | date_range_last_n | 3 | 6721 | 0.00113389 | 5761 | True |
| comparisons-004 | comparisons | 2 | 2792 | 0.00030628 | 4381 | True |
| single_game_narrative-004 | single_game_narrative | 4 | 7594 | 0.00145040 | 7067 | False |
| turning_points-004 | turning_points | 2 | 3350 | 0.00054989 | 2195 | True |
| aliases_typos-004 | aliases_typos | 3 | 5758 | 0.00083902 | 3803 | True |
| unsupported-004 | unsupported | 2 | 3290 | 0.00058655 | 3070 | True |
| exact_statistics-005 | exact_statistics | 3 | 5627 | 0.00081416 | 3557 | True |
| date_range_last_n-005 | date_range_last_n | 2 | 2963 | 0.00042067 | 2554 | True |
| comparisons-005 | comparisons | 4 | 8252 | 0.00119542 | 5398 | True |
| single_game_narrative-005 | single_game_narrative | 3 | 6204 | 0.00098628 | 5019 | True |
| turning_points-005 | turning_points | 3 | 6701 | 0.00134087 | 6331 | True |
| aliases_typos-005 | aliases_typos | 3 | 5911 | 0.00091611 | 5320 | True |
| unsupported-005 | unsupported | 2 | 3120 | 0.00047846 | 3378 | True |
| exact_statistics-006 | exact_statistics | 3 | 5638 | 0.00067619 | 3502 | True |
| date_range_last_n-006 | date_range_last_n | 3 | 6038 | 0.00088239 | 5415 | True |
| comparisons-006 | comparisons | 4 | 8205 | 0.00116496 | 6542 | True |
| single_game_narrative-006 | single_game_narrative | 5 | 10189 | 0.00127293 | 10058 | True |
| turning_points-006 | turning_points | 2 | 3580 | 0.00066476 | 3754 | True |

## What happens at the cutoff

`BudgetReservation.reserve` is a Lua check against the same `ai-budget:YYYY-MM` key. When the
total plus the reservation would exceed `OPENROUTER_MONTHLY_CUTOFF_USD`, it returns `None`.
`request_model` raises `RuntimeError("Budget unavailable")`; `AnalystLoop.run` catches it and calls
`fallback("Model or budget unavailable.")`. The user gets cited deterministic facts, HTTP 200,
`llm_validated=false`, `degraded=true`, and that warning. No provider call is made. The
`kill_switch` and `provider_failure` preflight checks exercise the same fallback path and verify
the delivered wins/losses against the active release.

The last fraction of the budget can degrade earlier than the raw dollar figure because each turn
reserves calls at `ANALYST_CALL_RESERVATION_USD` (default $0.01) before spending. A turn may hold
up to the six-call cap, so up to $0.06 can be reserved ahead of actual spend. Failed or timed-out
provider calls settle at the reservation amount, not zero: the preflight provider-failure probe
charged $0.01 for one failed call. An outage can therefore consume budget while delivering no
model answer.

A new UTC month changes the key and starts from zero. A missing key is treated as zero by the same
Lua script, so no seeding is required. The free Key Value instance has no persistence: a restart
loses the ledger, the next request starts a fresh one, and the undercount is bounded by one month's
spend. The runbook forbids silently restoring a missing ledger to zero; reconcile provider usage
and outstanding reservations first.

Budget is not the only ceiling. Public rate limits default to 10 per minute and 100 per day per
client. At the measured mean, the $2 budget supports about 73 questions per day over a month,
below the 100 per day single-client cap, so a single client hits its daily limit first. Multiple
clients can exhaust the monthly budget. The measurement did not test concurrency, so free-instance
CPU and provider concurrency limits are not quantified here.

## Latency gate result

`docs/evaluation.md` requires analyst p95 below four seconds before promotion. This sample
measured **p95 6,879.7 ms and p50 4,699.6 ms**, so the latency gate is **not met**. The best
observed request was 2,195 ms and the worst 10,058.5 ms. HTTP errors were zero, but four of 40
turns degraded to deterministic facts, so the model-validated rate was 90 percent.

This is a launch blocker, not a cost result: promotion stays blocked unless latency is reduced or
the owner explicitly approves a gate exception. See the owner decision list in
`docs/release-checklist.md#intended-launch-configuration`.

## Limits of this sample

- n=40. The p95 is the second-highest observation, not a stable tail estimate. Latency and cost
  spread are indicative, not an SLA.
- One model, one provider route, one day, one archive release, one region. OpenRouter routing,
  price changes, or a release with different evidence sizes can move both numbers.
- The app ran in-process, so Render network latency, cold starts, and free-instance CPU contention
  are excluded. The model round trip, which dominates the latency, is included.
- Qdrant was disabled. The evidence loop did not query it in these turns, but production enables
  Qdrant Cloud Inference and hybrid retrieval for other paths.
- The sample is a fixed evaluation set, not production traffic. Category counts are balanced by
  design; real traffic may skew toward cheap unsupported questions or expensive narratives.
- Rate limits were raised for the run. Costs are unaffected, but throughput is not representative.
- Costs are what the application ledger charged for these 40 turns. Provider invoice rounding,
  credits, and cache discounts are outside the ledger and not modeled.
- Four turns fell back after validation failure. Their cost is included; their quality is not a
  capacity result. Quality is measured separately by the live E2E and audit workstreams.
