# llm_primary cost: the 10x, the reconciliation, and the real capacity at $2

Measured 2026-10-21 on the local restored release `2025-26.20260928.1`, real OpenRouter
provider, model `deepseek/deepseek-v4.1-flash`, Redis db 14. Final head `bbb5296`; the
controlled A/B ran on `5f6fe82`, which has the same writer/reviewer behaviour and no cost
change between the two. 40 live questions total: 2 harness smoke, 20 mixed production, 10
high-reasoning A/B, 6 + 2 on the final head. No other worker's Redis db was written.

## Answer

The 10x is not a production cost curve. It is two compounding defects plus a routing
difference:

1. The held-out run did not set `AI_REASONING_EFFORT=none`, which is the production value.
   The model spent its completion budget on reasoning tokens, returned `null` content with
   `finish_reason=length`, and the reviewer could not parse a verdict. 59 of the 294 traced
   calls in the 60 delivered held-out rows failed this way (53 review, 5 revise, 1
   orchestrate). The held-out run scored 5/60 on the honest `meets_expectation` check.
2. On a failed call after a provider response, cost accounting discarded the provider's
   reported `usage.cost` and settlement charged the flat $0.01 call reservation. In the
   controlled reproduction, 12 failed calls were billed $0.018147 by the provider and
   charged $0.120000 by the ledger. Those calls carried real prompt tokens and a truncated
   completion, so the provider invoice is real; the extra $0.0085 per call is phantom.
3. OpenRouter routing is unpinned (`sort: latency`). The same model costs $0.0342/$0.1368
   per million prompt/completion tokens on Baidu and $0.30/$1.20 on Together, a 8.8x spread,
   with a $0.60/$2.40 endpoint in the same list (17.5x). The db6 run's costs fit
   $0.0818/$0.620 per million, so it ran a much cheaper route than the held-out run, whose
   successful calls were on Together. On the same 10 questions and the same 32 calls, our
   Together route cost 1.27x the db6 run.

Controlled A/B, same 10 hard questions, same commit `5f6fe82`:

| Setting | Calls | Failed | Ledger | Provider reported | Phantom | Validated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| production reasoning (`none`) | 37 | 0 | $0.015590 | $0.015590 | $0.000000 | 9/10 |
| reasoning unset (reproduced with `high`) | 47 | 12 | $0.147864 | $0.046011 | $0.101853 | 1/10 |

The ledger ratio is 9.48x. It decomposes exactly: real provider usage rose 2.95x
(reasoning tokens plus retries) and the ledger overstated the resulting usage by 3.21x
(flat failed-call settlement). 2.95 x 3.21 = 9.48. The phantom share of the high-reasoning
ledger is 68.9 percent.

## Reconciliation

Every fresh run closes the ledger against settlements and retained reservations with
`ledger_delta = sum(settled) + open_after - open_before`. The residual is zero to 1e-9 in
all 38 fresh questions; `summary.json` in each run records `reconciles: true`.

| Run | Questions | Calls | Failed | Ledger delta | Settled | Open delta | Reported usage | Residual |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `prod-none` | 20 | 69 | 0 | $0.028295916 | $0.028295916 | $0.000000000 | $0.028295916 | $0.000000000 |
| `reasoning-high` | 10 | 47 | 12 | $0.147863664 | $0.147863664 | $0.000000000 | $0.046010676 | $0.000000000 (phantom $0.101852988) |
| `final-head` | 6 | 21 | 0 | $0.010692048 | $0.010692048 | $0.000000000 | $0.010692048 | $0.000000000 |
| `final-head-check` | 2 | 5 | 0 | $0.002185992 | $0.002185992 | $0.000000000 | $0.002185992 | $0.000000000 |

Historical runs, from their committed artifacts plus the Redis snapshot:

| Run | Ledger | Reported / reconcilable | Open | What closes and what does not |
| --- | ---: | ---: | ---: | --- |
| db6 ops, 40 q | $0.036241280 | $0.036241270 | $0.000 | Closes to $0.000000010, the committed per-row rounding. 120 calls, 0 failed. |
| db2 held-out, 84 attempts | $1.146562208 | 59 traced failed calls x $0.01 = $0.590000 flat; reported usage of the 235 traced successful calls is at most $0.556562 | $0.000 | Cannot close exactly: 24 rerun attempts were not retained, and traces pre-date token metadata. The flat component is at least 51.5 percent of the ledger; rerun failures add more. |
| db1 registry, 49 q | $0.594955166 | Not reconstructable: committed responses have no provider trace | $0.012 (6 x $0.002) | Open reservations are 2.0 percent of the ledger, not the 10x. |

`historical-reconciliation.json` holds the machine-readable numbers. The db2 reservation
value is the config default $0.01; the scoring command in its README does not override
`ANALYST_CALL_RESERVATION_USD`. If that worker set a smaller value off-record, the flat
component scales down and the reported-usage ceiling rises, but the mechanism does not
change.

## Candidate causes, each ruled in or out

| Candidate | Verdict | Evidence |
| --- | --- | --- |
| Non-question calls (probes, reruns) | In, minor | db2 is 84 attempts for 60 delivered questions: 24 reruns, 28.6 percent of attempts and 40 percent more attempts than delivered. db6 and our runs had none. Cannot produce 10x. |
| Reserved-but-unsettled amounts | Out as main cause | db2 had 0 open at read; db1 has 6 x $0.002 = $0.012 (2.0 percent); our runs 0. Reservations are held in the ledger by design, so an aborted process leaks a reservation. |
| Review/repair retries | In, contributing | db2: 294 calls for 60 questions (4.9/q), 91 review + 50 revise, 45/60 ended `fallback:review_rejected`. Production 20-question run: 3.45 calls/q; hard 10: 3.7/q; ops 10: 3.3/q. |
| Reasoning tokens billed | In, dominant | High-reasoning run: 24,263 reasoning tokens of 30,246 completion tokens (80.2 percent), 15 `finish_reason=length`, 11 null-content failures. Production run: 0 reasoning tokens, 69/69 stop. |
| Provider routing to a pricier upstream | In, ~1.27x same-work factor, up to 17.5x per-token spread | db2 successful calls: Together 188, Reka 34, BaseTen 13. db6 implied $0.0818/$0.620 per million; Together list $0.30/$1.20. Identical 10 questions, identical 32 calls: db6 $0.009981, ours $0.012706 (1.273x). Adapter sends `sort: latency`, not price. |
| Settlement uses a different field | Out | 69/69 production calls and 35/35 successful high-reasoning calls settled at exactly the provider's `usage.cost` (difference below 1e-9). The divergence is only on failed calls. |
| Held-out questions take the long path | In, modest | 4.9 calls/q on held-out versus 3.45 production and 3.0 db6. Under production reasoning the hard 10 cost only 1.23x the ops 10 ($0.001559 versus $0.001271 per question). |
| Failed calls settle at the flat reservation | In, dominant for db2 | See the accounting section. 59 traced failures x $0.01 = $0.590000, at least 51.5 percent of db2. Reproduction charges $0.12 for $0.018147 of real usage. |

## Corrected capacity at $2

Production configuration (`AI_REASONING_EFFORT=none`, `ANALYST_REASONING_EFFORT=none`),
current writer and reviewer, 20 mixed questions. Capacity is `floor(2 / mean)` before the
in-flight reservation margin (up to 6 x $0.01 = $0.06).

| Question type | n | Calls | Mean cost | Capacity at $2 | Mean at Baidu prices | Capacity at Baidu prices |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| unsupported | 1 | 2 | $0.000796 | 2,513 | $0.000091 | 22,051 |
| exact_statistics | 3 | 10 | $0.001112 | 1,798 | $0.000127 | 15,775 |
| comparisons | 4 | 14 | $0.001264 | 1,582 | $0.000144 | 13,882 |
| single_game_narrative | 4 | 14 | $0.001345 | 1,486 | $0.000153 | 13,039 |
| aliases_typos | 1 | 3 | $0.001534 | 1,303 | $0.000175 | 11,436 |
| turning_points | 3 | 11 | $0.001676 | 1,193 | $0.000191 | 10,469 |
| date_range_last_n | 4 | 15 | $0.001792 | 1,116 | $0.000204 | 9,792 |
| All 20, measured route (Together/BaseTen) | 20 | 69 | $0.001415 | 1,413 | $0.000161 | 12,400 |
| Ops-shaped 10 | 10 | 33 | $0.001271 | 1,574 | - | - |
| Held-out-shaped 10 | 10 | 37 | $0.001559 | 1,282 | - | - |

Median per-question cost is $0.001401 (1,427 questions); p95 is $0.001987 (1,006). The final
head sample (`bbb5296`, 8 questions) averaged $0.001610, capacity 1,242; the small sample
includes three degraded turns and is consistent with the 20-question run.

The Baidu columns are an exact counterfactual: the same token counts repriced at the cheapest
listed endpoint for this model. They are not a route we can select today because the adapter
does not pin a provider. Real capacity therefore sits between about **1,200 and 1,400
questions per month at today's routing**, and about **10,000 to 12,000** if routing is pinned
to the cheapest endpoint. The public rate limit of 100 questions per day per client caps a
single client at about 3,000 per month, so the high end needs multiple clients or a raised
limit.

Neither historical figure is the production number. The db6 $0.000906 (2,207/month) came
from a cheaper route and does not record the reasoning setting; the db2 $0.013650
(146/month) is the defect. For reference, the same defect reproduction would still buy 434
questions if the flat charge were corrected to the provider-reported usage, and 135 at the
uncorrected ledger.

## Accounting bug: failing case recorded first

Case: `accounting-failure-case.json`, from `reasoning-high/calls.jsonl`. Twelve calls failed
after the provider had already sent a response. Eleven had `content_kind=null`,
`finish_reason=length`, `reasoning_tokens=1200` and a real prompt token count; one had no
response (timeout). The provider reported $0.018147 for those calls; settlement charged
$0.120000.

Expected: when the HTTP response carries `usage.cost`, settle at that cost even if the
content cannot be parsed. Charge the reservation only when there is no response at all.

Actual on `bbb5296`: `report_llm` stores usage before raising, but `request_model` reads
`adapter.last_metadata` only after `await adapter.generate` returns. On exception the local
metadata stays empty, `loop.costs[-1]` stays `None`, and `AnalystLoop.settle` substitutes
the $0.01 reservation for that slot. The ledger overstates by $0.0085 per failed call in
this sample.

Fix: LatencyCut implemented the minimal change in `codex/llmp-latency` at `387b11a`:
`request_model` now catches the exception, reads the adapter metadata, writes
`usage.cost` into `loop.costs[-1]` when present, and re-raises. A call with no HTTP response
still settles at the reservation. That branch is not merged into `codex/llmp-integration`
at the time of this report, and the fix was not re-measured live (budget exhausted). I did
not edit `analyst_provider.py` or `analyst_loop.py`; the finding and the failing case were
sent to LatencyCut.

The commit that introduced the production reasoning value also changed the effective knob:
`request_model` overrides `adapter.reasoning_effort` from `settings.analyst_reasoning_effort`
(default `none`), so `AI_REASONING_EFFORT` alone no longer controls analyst calls. Use
`ANALYST_REASONING_EFFORT` to reproduce the defect on `bbb5296`.

## Limits

- 20 mixed questions, one release, one day, one key, in-process ASGI. Provider routing is
  not controllable, so the measured route is what OpenRouter chose during these minutes.
- Category cells are 1 to 4 questions. The type table is indicative, not a per-category SLA.
- Quality is not measured here. The 20-question production run validated 18/20; the
  high-reasoning run validated 1/10, which is why its cost is a defect artifact, not a
  capacity input.
- The held-out question file was never read. Only trace metadata (stage, provider, outcome)
  and aggregate counts from the committed response artifact were used.
- Redis db2 and db1 belonged to other workers and were read only. Their ledgers continued to
  grow after the reads recorded here because those workers were still active.
- The provider key is shared by every worker. `provider-and-ledger-snapshot.json` records
  the key's daily/monthly usage beside the ledger snapshot; the two are not a clean
  one-to-one reconciliation because other dbs were active.

## Reproduction

```sh
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
REDIS_URL=redis://localhost:56500/14 RAG_QDRANT_ENABLED=false \
ANALYSIS_ANSWER_MODE=llm_primary ANALYST_EVIDENCE_LOOP_ENABLED=true \
AI_PROVIDER=openrouter AI_BASE_URL=https://openrouter.ai/api/v1 \
AI_CHAT_MODEL=deepseek/deepseek-v4.1-flash AI_REASONING_EFFORT=none \
OPENROUTER_MONTHLY_CUTOFF_USD=2 \
uv run --package knicksiq-api python tools/release/measure_llm_cost.py \
  --questions docs/release-evidence/llm-primary-20261021/cost/questions.mixed.jsonl \
  --out-dir docs/release-evidence/llm-primary-20261021/cost/prod-none --label production-none
```

The high-reasoning reproduction used the same command with `AI_REASONING_EFFORT=high` on
`5f6fe82` before the latency merge, and the hard 10 rows of `questions.mixed.jsonl`.

## Artifacts

- `questions.mixed.jsonl`: 10 question ids used by the ops run plus 10 authored
  held-out-shaped questions in the failing categories. None comes from the held-out set.
- `prod-none/`: the 20-question production run; `calls.jsonl` has stage, reservation,
  reported cost, settled cost, prompt/completion/reasoning/cached tokens, provider,
  finish_reason, content_kind and request id per call.
- `reasoning-high/`: the 10-question defect reproduction.
- `final-head/`, `final-head-check/`: post-merge samples on `bbb5296`; the six-question
  run's cost fields are valid but its stage labels were mapped before the harness learned
  about the new prepare/tool trace entries. The two-question check validates the corrected
  mapping.
- `accounting-failure-case.json`, `historical-reconciliation.json`,
  `provider-and-ledger-snapshot.json`: the failing case, historical run arithmetic, and the
  provider price/ledger snapshot.
