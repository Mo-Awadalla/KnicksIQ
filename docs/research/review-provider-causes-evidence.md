# Evidence detail: payload budget, stage fingerprint, and record gaps

Companion to `docs/research/review-provider-causes.md`. All line numbers are HEAD `d580011`
(`codex/production-ready-20261018`). Measurements were produced with the repository's own models
and helpers (`VerifiedClaim.create`, `claim_view`, `token_upper_bound`, `compact_schema`,
`INTERPRETATION_POLICY`) in the project venv; no provider calls, no database access, no code
changes.

## 1. Payload limits and component sizes

`token_upper_bound` returns the UTF-8 byte length of the encoded value
(`apps/api/app/services/analyst_provider.py:34-37`), so every "token" budget below is really a byte
budget. `build_payload` limits its own payload to `analyst_input_tokens - instruction_bytes`
(`analyst_provider.py:194-196`), where `instruction_bytes` is the byte length of the system prompt
passed at `analyst_provider.py:322-327`; `request_model` then checks
`system + payload (+ response schema)` against the same total (`analyst_provider.py:341-349`).

With the defaults from `apps/api/app/core/config.py:122-130` (`analyst_input_tokens=8000`) and the
repository `.env` (no `ANALYST_*` override, `analyst_provider_format` stays `json_object`):

| quantity | bytes |
| --- | --- |
| writer system prompt (`analyst_provider.py:295-319`) | 1,705 |
| + repair suffix (`analyst_provider.py:320-321`) | 75 |
| review system prompt (`analyst_provider.py:270-292`) | 1,515 |
| payload limit, action/answer call | 6,295 |
| payload limit, repair call | 6,220 |
| payload limit, review call | 6,485 |
| `compact_schema(Action)` | 1,858 |
| `compact_schema(ProposedAnswer)` | 829 |
| `compact_schema(AnswerReview)` | 1,430 |
| `INTERPRETATION_POLICY` (`evidence_contracts.py:19-27`) | 590 |
| capabilities manifest (`analyst_tools.manifest`, 101 games) | 929 |
| one `results[]` entry for `get_team_stats` | 424 |

Claim sizes as the model sees them (`claim_view`, `analyst_provider.py:123-134`). `AnalystTools.claim`
collapses more than three supporting receipts into a single calculation receipt
(`analyst_tools.py:252-275`), which is why a 101-game claim is no larger than an 8-game one:

| claim | bytes |
| --- | --- |
| team claim, 8-game window (wins / losses / points per game / margin per game) | 545 / 551 / 588 / 584 |
| team claim, 101-game population (same four) | 551 / 557 / 594 / 590 |
| `player()` claim, 93 appearances | 693 |
| `discover_facts` rank claim (recent vs baseline) | 1,024 |

## 2. Repair payload: why the reviewer dump decides it

`validate` returns the whole reviewer object as the repair reason
(`analyst_loop.py:262-263`), and `request_model` puts it in the next payload verbatim as `repair`
(`analyst_provider.py:322-327`). The repair call therefore carries:

```
schema ProposedAnswer 829 + policy 590 + manifest 929 + question/context/rounds ~92
+ one result entry 424 + rejected answer dump 559 = 3,423 bytes
```

against a 6,220-byte limit, before the reviewer dump, any claims and any evidence. Sizes of the
reviewer dump (`AnswerReview` with one assertion per sentence span, 64-char claim ids and
1–3 evidence ids per assertion):

| review span count and reason length | bytes |
| --- | --- |
| 2 spans, 150-char reasons | 853 |
| 2 spans, 300-char reasons | 1,119 |
| 3 spans, 150-char reasons | 1,281 |
| 3 spans, 300-char reasons | 1,680 |
| 5 spans, 150-char reasons | 2,109 |
| 5 spans, 300-char reasons | 2,774 |
| 6 spans, 300-char reasons | 3,348 |

So a repair after a five- or six-assertion review of a narrative answer cannot be assembled even
with no claims and no evidence in the payload; with two or three tool results the threshold is
lower still. The two affected questions take the `search_archive` / `discover_facts` path, which
adds a `results[]` entry per tool call (424 B for a team result) and up to ten `Candidate` objects
(`analyst_discovery.py:288-310`).

## 3. Why `failed:review:ValueError` can only be payload assembly

`AnalystLoop.run` catches every exception from `investigate()` and returns
`fallback("Model or budget unavailable.")` (`analyst_loop.py:120-131`). The harness records only
`error_type` and the last trace stage (`tools/release/analyst_live_e2e.py:32-45`) and labels the row
`failed:<stage>:<error_type>` (`tools/release/analyst_live_e2e.py:68-72`). The trace entry is
appended in `request_model`'s `finally` (`analyst_provider.py:360-382`) with
`stage = "review" if review else "revise" if repair else "orchestrate"`. Therefore:

| raising site | error type | last trace stage the harness sees |
| --- | --- | --- |
| `build_payload` base overflow (`analyst_provider.py:194-196`), action/answer call | ValueError | previous call's stage (none → `orchestrate` of the failure log's fallback) |
| same, **repair** call | ValueError | **`review`** (review call already appended) |
| `build_payload` review claim group (`analyst_provider.py:226-231`) | ValueError | previous stage; caught at `analyst_loop.py:249-254` |
| `mandatory_bytes` guard (`analyst_provider.py:341-349`) | ValueError | previous stage; needs `json_schema` format to fire |
| pydantic `ValidationError` on model JSON (`analyst_provider.py:366`) | ValidationError | `review`/`revise`/`orchestrate` of *that* call |
| `ValueError("Tool action exceeds output cap")` (`analyst_provider.py:367-368`) | ValueError | same call's stage (`revise` or `orchestrate`) |
| call/deadline limit (`analyst_provider.py:264-265`) | TimeoutError | same call's stage |
| reservation refused (`analyst_provider.py:266-268`) | RuntimeError | same call's stage |
| `next_action` malformed action (`analyst_loop.py:165-174`) | ValueError | `orchestrate` |
| tool-call limit (`analyst_loop.py:188`) | ValueError | `orchestrate` |

Two consequences:

- A `ValueError` at stage `review` (the two rows in question) cannot come from the review call
  itself: anything raised inside its `try` still appends a `review` trace, and anything raised
  before it (payload assembly) would leave the previous stage. It can only come from the **repair**
  call's `build_payload` — i.e. the base context was already too large before any claim or evidence
  was considered.
- A `ValueError` at stage `orchestrate` (seen for `turning_points-003` in `after-fix4-n70.json`) is
  either the same payload overflow on an action call or one of the two explicit loop guards
  (`analyst_loop.py:165-174`, `188`). The stage history below shows the same question changing stage
  between runs, which fits a size-driven failure and not a stable reviewer verdict.

Per-run history of the seven ids, from the `not_validated` lists of each file. `n/s` = id not
sampled: the 35-question runs take the first five questions of each category
(`tools/release/analyst_live_e2e.py:47-56`), so five of the seven ids were absent. `-` = the id was
sampled and is absent from `not_validated`, i.e. `llm_validated: true` (for an answerable question
that can still be a reviewer-accepted decline; the files keep only failures).

| id | baseline | after-fix1 | after-fix2 | after-fix3 | after-fix4-n70 | final3 |
| --- | --- | --- | --- | --- | --- | --- |
| `exact_statistics-009` | n/s | n/s | n/s | n/s | - | `fallback:review_rejected` |
| `date_range_last_n-007` | n/s | n/s | n/s | n/s | - | `validated_declined` |
| `comparisons-002` | `failed:review:ValueError` | `failed:review:ValueError` | - | - | - | `fallback:review_rejected` |
| `unsupported-006` | n/s | n/s | n/s | n/s | - | `fallback:review_rejected` |
| `unsupported-008` | n/s | n/s | n/s | n/s | `fallback:review_rejected` | `fallback:review_rejected` |
| `turning_points-003` | `fallback:review_rejected` | `fallback:review_rejected` | `failed:review:ValueError` | - | `failed:orchestrate:ValueError` | `failed:review:ValueError` |
| `aliases_typos-010` | n/s | n/s | n/s | n/s | `fallback:review_rejected` | `failed:review:ValueError` |

`comparisons-002` failed at stage `review` with `ValueError` in two runs, was reviewer-accepted in
`after-fix2`/`after-fix3`/`after-fix4`, and was rejected in `final3`; `exact_statistics-009` was
reviewer-accepted in `after-fix4` and rejected in `final3`. `aliases_typos-010` moved from
`fallback:review_rejected` to `failed:review:ValueError`. The flips are consistent with a payload
that sometimes overflows and sometimes leaves room for one more claim, and with a reviewer whose
verdict changes with the writer's wording; neither the wording nor the verdict is recorded.

## 4. Claim-admission replay for `date_range_last_n-007`

The delivered answer names wins (7), losses (1) and points per game (110.25) and states there is no
margin value. `team()` emits all four claims for `aggregation="average"`
(`analyst_calculations.py:108-114`) in the order wins, losses, points per game, margin per game, and
`build_payload` admits them group by group while the projected payload fits
(`analyst_provider.py:199-235`). Replaying that rule with the real models (the `Action` schema, one
`get_team_stats` result, the eight-game scope):

```
base payload                                          4,072
+ wins                                                 4,601  admitted
+ losses                                               5,137  admitted
+ points_per_game                                      5,726  admitted
+ margin_per_game                                      6,311  > 6,295 limit → skipped
```

The margin claim misses by 16 bytes. Small perturbations of the base (a longer question, a second
`results[]` entry, a different `relative_game_count` in the scope dump) change which claim is last,
but not the mechanism: the loop keeps the first claims in result order and drops the rest without
telling the writer.

## 5. What the outcome labels hide

- `classify` derives `fallback:review_rejected` from the substring "evidence review" in the warning
  (`tools/release/analyst_live_e2e.py:73-75`). That warning is emitted after a failed repair
  regardless of why the repair was needed. Three paths reach it: `validate_structure` failed
  (`analyst_loop.py:238-248`), the reviewer returned a non-passing verdict
  (`analyst_loop.py:262-263`), or the reviewer call failed with `ValueError`/`RuntimeError` and
  became "Reviewer failed or returned malformed output." (`analyst_loop.py:249-254`). The last
  includes reviewer-payload budget failures (`analyst_provider.py:226-231`), so some
  "review rejected" rows may be budget failures.
- `validate_structure` enforces six rules — claim present and same release, displayed value equality
  or rounding, baselines present, evidence present and same release, candidate `fact_id` coverage,
  `fact_ids` resolvable (`evidence_contracts.py:217-249`) — but the repair hint mentions only
  `displayed_value` (`analyst_loop.py:245-248`). A candidate/`fact_id` or baseline failure gets a
  hint that cannot fix it, burns the single repair, and is then labelled "review rejected".
  [INFERENCE] this is a plausible contributor to the review-rejected rows; the records cannot
  confirm or exclude it.
- `AnalysisQueryResponse` exposes `warnings`, `degraded` and `llm_validated` but hides `route` and
  `tool_calls` in production (`apps/api/app/api/analysis_models.py:82-113`), and no field carries a
  failure code, stage, or the rejected wording. These rows cannot be diagnosed from a production
  response.

## 6. Evidence and limits

Observed: the seven response rows; the per-run history above; the label-draft facts for all seven
ids (`docs/release-evidence/evaluation-label-drafts.jsonl:9,32,78,105,111,113`); code at HEAD; the
byte measurements and the admission replay.

Not observed: the rejected wording for the five `fallback:review_rejected` rows; the per-call
payload for the two `ValueError` rows; the reviewer's verdicts and reasons. Consequently the
specific rule that failed review for `exact_statistics-009` and `comparisons-002` is marked as
inference. The contract-level argument, the deterministic fallback text, the claim-admission
replay, and the `ValueError` stage fingerprint are not inferred.
