# Provider routing: per-upstream evidence and the offline decision

Branch `codex/llmp-w3-routing` from `codex/llmp-integration` at `5b585e6`. Worktree
`~/.local/share/knicksiq/worktrees/w3-routing`, Redis db 4, live budget 150 questions.

Status: OFFLINE COMPLETE, LIVE BLOCKED. The OpenRouter account behind `AI_API_KEY` is out of
credits. `GET /api/v1/credits` returns `total_credits 35`, `total_usage 35.159`; every chat
call returns HTTP 402 `in_flight_budget_exhausted`, including direct probes and two one-question
smoke runs at 01:22 and 01:25 UTC. The alternate key in
`~/.local/share/knicksiq/secrets/openrouter.env` belongs to the same account. Two smoke rows
returned 402 and are discarded, not scored. No live arm ran, so the chosen provider order and
the before/after p50/p95/cost/validated table remain pending. Everything below is either an
offline deterministic check or an analysis of already-recorded dev-set responses.

## Code change

`apps/api/app/services/report_llm.py` builds the OpenRouter `provider` block from settings
instead of hardcoded values. `apps/api/app/core/config.py` adds:

| Setting | Default | Meaning |
| --- | --- | --- |
| `OPENROUTER_PROVIDER_ORDER` | `[]` | Preferred upstreams, tried in order. Empty preserves the router's choice. |
| `OPENROUTER_PROVIDER_SORT` | `latency` | `latency`, `throughput`, `price` or `none` (omit the key). |
| `OPENROUTER_PROVIDER_ALLOW_FALLBACKS` | `true` | Whether OpenRouter may leave the listed order. |

There are no upstream names in code paths; a name can only appear in a deployment setting or a
config default. `require_parameters: true` is unchanged and still applied whenever a structured
response is requested, so a pinned upstream that lacks `response_format` support is skipped
rather than sent an unsupported parameter. The default payload is byte-identical to the
pre-change payload (`{"allow_fallbacks": true, "sort": "latency", "require_parameters": true}`),
which is why the existing adapter test passes unchanged.

`payload-probe.json` is the deterministic check: it captures the exact request body for the
default, a pinned order, pinned with fallbacks off, `sort: none`, and a settings-built adapter.
All nine assertions pass (`payload_probe.py` exits 0).

## Routing semantics probes

Eight direct chat calls with `max_tokens` 8 and `reasoning: none` were made before the credits
ran out. They are not app questions and cost about $0.00002 in total.

| Request | Response provider |
| --- | --- |
| `order: ["Decart"]`, `allow_fallbacks: false` | Decart |
| `order: ["Together"]`, `allow_fallbacks: false` | Together |
| `order: ["Decart"]`, `allow_fallbacks: false`, `sort: latency` | Decart |
| `order: ["Together", "Decart"]`, `allow_fallbacks: true`, `sort: latency` | Together |
| `order: ["Together", "Decart"]`, `allow_fallbacks: true`, no sort | Together |
| `sort: price`, no order | OpenInference, then Relace on repeat |

This confirms the behavior the settings rely on: `order` wins over `sort`, a listed first
upstream is used when fallbacks are disabled, and `sort: price` alone does not keep a provider.
It does not measure quality or latency; those need the pending app arms.

## Recorded per-upstream table

Source: `analyze_recorded.py` over the committed dev-set traces of `final/budget-16000`,
`final/budget-8000`, `final/budget-8000-drops`, `latency/{base-gate,after-gate,after-premerge-40}`.
That is 1,269 provider calls across 451 question rows. Held-out artifacts were not read. These
responses were produced under the unpinned router, so provider assignment is not random; treat
the table as a description of the routing that actually happened, not a controlled
per-provider experiment.

| Provider | Calls | Stages | p50 ms | p95 ms | finish | Answer questions | Answer validated | Review questions | Review validated |
| --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| Together | 1084 | answer:450 plan:287 review:226 repair:121 | 813.6 | 2095.0 | stop 1084 | 442 | 0.767 | 221 | 0.968 |
| Reka | 178 | answer:6 review:137 repair:35 | 1535.0 | 3233.0 | stop 178 | 6 | 0.500 | 135 | 0.941 |
| BaseTen | 7 | plan:3 answer:1 review:3 | 921.0 | 3068.6 | stop 7 | 1 | 0.000 | 1 | 1.000 |

Per stage, same calls:

| Stage | Provider | Calls | p50 ms | p95 ms |
| --- | --- | ---: | ---: | ---: |
| plan | Together | 287 | 471.0 | 1009.0 |
| plan | BaseTen | 3 | 739.1 | 921.0 |
| answer | Together | 450 | 879.0 | 2157.0 |
| answer | Reka | 6 | 1698.0 | 4221.0 |
| answer | BaseTen | 1 | 573.0 | 573.0 |
| review | Together | 226 | 1371.2 | 2787.0 |
| review | Reka | 137 | 1560.0 | 2948.0 |
| review | BaseTen | 3 | 2310.0 | 3068.6 |
| repair | Together | 121 | 721.0 | 1748.0 |
| repair | Reka | 35 | 1250.0 | 3308.0 |

"Answer validated" is the validated rate of questions whose last answer-stage call used that
upstream; "Review validated" is the same for the last review call. A question has one answer and
at most one retained review, so the denominators differ from the call counts. Reka answered only
6 questions, so its 0.500 is 3/6, not a stable rate. BaseTen has 7 calls and no usable estimate.
Every recorded call returned `finish_reason=stop` with string content and no reasoning tokens,
so content failures do not separate these upstreams in this sample.

Cost is available per call only in `cost/prod-none/calls.jsonl` (69 calls, 20 questions):

| Provider | Calls | Prompt tokens | Completion tokens | Reported $ | Reported $ per 1M prompt tokens (blended) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Together | 67 | 112,261 | 13,535 | 0.02688952 | 0.2395 |
| BaseTen | 2 | 3,304 | 346 | 0.00140640 | 0.4257 |

The blended column divides total reported cost by prompt tokens, so it includes completion cost;
it is a relative comparison, not a list price. The endpoint list fetched at measurement time
ranges from $0.07/$0.50 per million prompt/completion tokens (OpenInference, Relace) to
$0.60/$2.40 (one BaseTen endpoint), the 8.6x prompt and 13.3x completion spread behind the 17.5x
blended figure in `cost/README.md`. The recorded traffic never reached the cheapest endpoints:
together served 85 percent of calls across these six runs.

## Latency composition and the 4 s gate

From the shipped 16,000-byte run (`final/budget-16000.rows.jsonl`, 140 questions, production
settings, reasoning none):

| Group | Questions | p50 ms | p95 ms |
| --- | ---: | ---: | ---: |
| All | 140 | 3295.8 | 7640.5 |
| 2 model calls (answer + review) | 60 | 2347.8 | 4098.3 |
| 3 model calls | 53 | 3454.3 | 6230.1 |
| 4 model calls | 21 | 4729.1 | 9386.1 |
| 5 or 6 model calls | 4 | 10720.1 | 13752.8 |

Per-call p50/p95: plan 805.5/2298, answer 879/2157 (call p95), review 1526/3517, repair 873/2118.
Even the 2-call shape has p95 4,098 ms, so the 4 s gate needs two things together: almost every
turn reduced to answer + review, and a per-call tail near 1.7 s. Pinning the fastest upstream
attacks the second; eliminating planning calls (prefetch, another workstream) attacks the first.
The reviewer cannot be removed, so its 1.5 s p50 stays in every turn.

## Call-count reduction that keeps the reviewer

Recorded 16,000-byte run: 384 model calls for 140 questions, 2.74 per question.

- Review retry on `ValidationError`: 0 consecutive review calls in 140 question sequences, so
  the retry cost nothing in this sample and removing it would not reduce calls here.
- Repair: 53 `revise` calls (13.8 percent of calls). 14 of the 53 questions were validated after
  the repair; the other 39 ended in fallback, and 42 of the repairs never reached a review because
  the repaired answer failed deterministic structure checks. Dropping repair entirely would cut
  53 calls but lose 14/140 validated answers (10 percent). Quality first rejects that trade.
- The remaining call-count lever is the planning call, owned by the prefetch workstream; it is
  not changed here.

No call-count reduction is therefore proposed by this workstream on the recorded data. The
pending live arms will confirm whether pinning reduces failed reviews and therefore repairs.

## Pending live measurement (blocked on credits)

The acceptance sample is the 40-question round-robin sample from `questions.jsonl`. Two arms x
2 trials x 40 questions is 160 live questions, which exceeds the 150-question fence. The measured
set is 37 of those 40 (the first five round-robin rows per category; the sixth round drops three
entries), identical in both arms and both trials: 37 x 2 x 2 = 148 questions, leaving 2 for a
smoke. `measure_routing.py` records provider, stage, latency, reported cost, finish_reason,
content_kind and JSON parse outcome per call, plus the per-question outcome and honest score.

Baseline arm (current default routing, no order):

```sh
AI_API_KEY=... DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
REDIS_URL=redis://localhost:56500/4 ANALYSIS_ANSWER_MODE=llm_primary \
ANALYST_EVIDENCE_LOOP_ENABLED=true RAG_QDRANT_ENABLED=false AI_REASONING_EFFORT=none \
AI_PROVIDER=openrouter AI_BASE_URL=https://openrouter.ai/api/v1 \
AI_CHAT_MODEL=deepseek/deepseek-v4.1-flash OPENROUTER_MONTHLY_CUTOFF_USD=2 \
uv run --package knicksiq-api python \
  docs/release-evidence/llm-primary-20261021/w3-routing/measure_routing.py \
  --label before-unpinned --questions 37 --trials 2 \
  --out-dir docs/release-evidence/llm-primary-20261021/w3-routing
```

Flush db 4 before the first arm (`redis-cli -p 56500 -n 4 flushdb`). Then pick the upstream by
the stated order: quality first (answer and review validated rates, no content failures), then
p95 call latency, then reported cost. Run the pinned arm with that order (template; replace
`PROVIDER` and optionally add a fallback):

```sh
OPENROUTER_PROVIDER_ORDER='["PROVIDER"]' OPENROUTER_PROVIDER_SORT=latency \
OPENROUTER_PROVIDER_ALLOW_FALLBACKS=true \
AI_API_KEY=... DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
REDIS_URL=redis://localhost:56500/4 ANALYSIS_ANSWER_MODE=llm_primary \
ANALYST_EVIDENCE_LOOP_ENABLED=true RAG_QDRANT_ENABLED=false AI_REASONING_EFFORT=none \
AI_PROVIDER=openrouter AI_BASE_URL=https://openrouter.ai/api/v1 \
AI_CHAT_MODEL=deepseek/deepseek-v4.1-flash OPENROUTER_MONTHLY_CUTOFF_USD=2 \
uv run --package knicksiq-api python \
  docs/release-evidence/llm-primary-20261021/w3-routing/measure_routing.py \
  --label after-pinned --questions 37 --trials 2 \
  --out-dir docs/release-evidence/llm-primary-20261021/w3-routing
```

Then:

```sh
uv run python docs/release-evidence/llm-primary-20261021/w3-routing/compare_routing.py \
  --before docs/release-evidence/llm-primary-20261021/w3-routing/before-unpinned.rows.jsonl \
  --after docs/release-evidence/llm-primary-20261021/w3-routing/after-pinned.rows.jsonl \
  --out docs/release-evidence/llm-primary-20261021/w3-routing/comparison.json
```

The recorded evidence makes Together the candidate: it served 85 percent of recorded calls, is
1.9x faster at p50 than Reka (813.6 vs 1535.0 ms), is faster in every stage, and its questions
validated more often. The live baseline is still required because today's router may choose
different upstreams, and because the cheap endpoints have almost no recorded call data. Do not
change the config default until the pinned arm shows no quality regression; if it does, keep the
order empty and report the measured p95.

## Owner decision

Pending the live arms. The decision rule is fixed: quality first (no validated-rate regression
and no content failures), then p95, then cost. The chosen value is one settings line, documented
here when measured. The default remains `[]` so the current behaviour is unchanged until then.

## Backend gate

On this branch: `TEST_MODE=true uv run pytest apps packages tools/report_audit` 439 passed;
`uv run ruff check apps packages migrations` all checks passed; `ruff format --check` 246 files
already formatted; `uv run pyright apps packages migrations` 0 errors, 0 warnings.

## Artifacts

- `measure_routing.py`: live runner (per-call provider/cost/finish/parse capture, per-question
  honest score, ledger delta). Not yet run to completion because of the 402 blocker.
- `compare_routing.py`: renders the before/after and per-upstream tables from two rows files.
- `analyze_recorded.py`, `recorded-upstream.json`: the recorded-response analysis above.
- `payload_probe.py`, `payload-probe.json`: offline request-body check, 9/9 assertions pass.

## Limits

- No live arm ran. Every number is from already-recorded dev-set responses produced by earlier
  workstreams under the unpinned router, with different input budgets and code revisions; the
  provider mix is confounded with run, question and revision.
- The 40-question x 2-trial acceptance table is pending, not delivered.
- The cost artifact is 69 calls from one 20-question run; per-provider cost estimates are
  indicative and the cheapest endpoints have no recorded usage.
- The 4 s p95 gate is not demonstrated. Recorded 2-call turns alone have p95 4,098 ms; the
  pending arms test whether pinning removes enough upstream tail to cross the gate.
