# Root causes of the 7 review/provider misses in `final3-n70`

Scope: the seven questions named in issue #46, from
`docs/release-evidence/llm-primary-20261018/final3-n70.responses.jsonl` (37/70
`meets_expectation`). Planning only: no application code changed. Measurements and the
per-run history are in [`review-provider-causes-evidence.md`](review-provider-causes-evidence.md).

Code read at HEAD `d580011` (`codex/production-ready-20261018`). The only uncommitted file in the
main worktree is `apps/api/app/services/analyst_loop.py` with `claims[:3]` → `claims[:6]`
(`git diff`); `git show HEAD:...analyst_loop.py` still has `claims[:3]`, which is the code the
`final3` run reflects, so all citations below are HEAD line numbers.

## Summary

| id | outcome (harness) | delivered text | primary cause | is the label adequate? |
| --- | --- | --- | --- | --- |
| `exact_statistics-009` | `fallback:review_rejected` | wins 0 / losses 32 / points 3421 over 32 games | reviewer strictness/variance: reviewer-accepted in `after-fix4`, rejected in `final3`; no extremum claim exists and the fallback population is all 32 losses | partly: hides which rule rejected and that the fallback population is wrong |
| `date_range_last_n-007` | `validated_declined` | "no margin value" | claim-budget truncation: the 4th team claim missed the byte budget by 16 | no failure is labelled at all; the decline is certified although the archive has the value |
| `comparisons-002` | `fallback:review_rejected` | Towns 19.2 / Brunson 26.5 pts per appearance | reviewer strictness/variance: failed with `ValueError` twice, reviewer-accepted in `after-fix2`-`after-fix4`, rejected in `final3`; no comparison claim type | partly: the review rejection is real, the fragile contract is not named |
| `unsupported-006` | `fallback:review_rejected` | record totals + "I don't have live…" | fallback cannot decline (delivers claims for an unanswerable question) | no: hides the fallback defect behind a review label |
| `unsupported-008` | `fallback:review_rejected` | one current-season stat, no decline | genuine bug in fallback relevance (future-tense question, no live-word match) | no: hides the fallback defect behind a review label |
| `turning_points-003` | `failed:review:ValueError` | wins 6 / losses 3 / points 1042 over 9 games | swallowed internal `ValueError` (payload assembly) mislabelled as model/budget outage | no: blames the provider/budget |
| `aliases_typos-010` | `failed:review:ValueError` | wins 69 / losses 32 / points 11750 over 101 games | same swallowed `ValueError` | no: blames the provider/budget |

Grouped by root cause (primary, one row each):

- **Swallowed internal `ValueError` reported as "Model or budget unavailable."** — 2 rows
  (`turning_points-003`, `aliases_typos-010`). Genuine bug + reliability defect.
- **Reviewer strictness/variance on questions the contract cannot make robust** — 2 rows
  (`exact_statistics-009`, `comparisons-002`). Both were reviewer-accepted in `after-fix4` and
  rejected in `final3`, so neither a fixed reviewer rule nor a fixed writer wording explains
  `final3`; the rejected text was not kept. The missing comparison/extremum claim type is what
  makes them fragile.
- **Claim-budget truncation in the model payload** — 1 row (`date_range_last_n-007`), proven by
  replaying the admission rule. Silent, and invisible to the reviewer.
- **Fallback cannot decline and ignores question intent** — 2 rows (`unsupported-006`,
  `unsupported-008`).
- **Budget/ledger** — 0 rows. Excluded (section 5).

Cross-cutting defect present in 6 of 7 delivered texts: `render_fallback` takes
`fallback_claims()[:3]` (`analyst_loop.py:301`, HEAD) while `team()` emits its claims in the order
wins, losses, points, margin (`analyst_calculations.py:108-131`). The first three claims are
therefore always wins/losses/points, and the metric the question asked for is always the one
dropped. The uncommitted `[:6]` fixes the count but not the ordering or the relevance problem.

## 1. `turning_points-003` and `aliases_typos-010`: a `ValueError` is mislabelled as a model outage

Questions: "When did the Knicks collapse against Atlanta?" / "What was NY's worst collpase?"
Delivered: a deterministic three-claim dump plus `warnings: ["Model or budget unavailable."]`,
`degraded: true`, `llm_validated: false`.

`AnalystLoop.run` wraps `investigate()` in a blanket `except Exception` and returns
`fallback("Model or budget unavailable.")` for *any* exception (`analyst_loop.py:120-131`). The only
place the real cause survives is a server log line carrying `error_type` and the last trace stage
(`analyst_loop.py:132-151`). The harness records exactly that pair
(`tools/release/analyst_live_e2e.py:32-45`) and turns it into `failed:<stage>:<error_type>`
(`tools/release/analyst_live_e2e.py:68-72`). So `failed:review:ValueError` means a `ValueError`
escaped after the reviewer call had already appended its trace entry.

Inside `request_model` the only `ValueError`s raised **before** the `try/finally` that appends the
trace are payload-construction failures: `ValueError("Required review/action context exceeds input
budget")` (`analyst_provider.py:194-196`) and, for review calls only, `ValueError("Full referenced
claims cannot fit reviewer input")` (`analyst_provider.py:226-231`). Everything else that raises
`ValueError` runs inside the `try` and therefore appends a trace for *that* call
(`analyst_provider.py:360-382`), which would label the row `orchestrate` or `revise`, not `review`;
`TimeoutError` and `RuntimeError` are different error types (`analyst_provider.py:264-268`).

Therefore the only sequence that produces `failed:review:ValueError` is: the writer answered, the
review call completed with a non-passing verdict (or failed inside the part caught at
`analyst_loop.py:249-254`), the loop started its single repair (`analyst_loop.py:219-232`), and
`build_payload` for that repair call raised because the *base* payload — before any claim or
evidence — already exceeded `analyst_input_tokens - len(system)`.

The repair hint is the entire reviewer JSON (`analyst_loop.py:262-263`), injected verbatim into the
next payload (`analyst_provider.py:322-327`). The repair call's base is ~3.4 KB with one tool result
against a 6,220-byte limit, and a five- or six-assertion review dump alone is 2.8–3.3 KB
Narrative questions produce exactly those multi-sentence answers.
`token_upper_bound` counts UTF-8 **bytes**, not tokens (`analyst_provider.py:34-37`), so the
"8,000-token" budget is about 2.3k real tokens.

The stage is not stable across runs for the same question: `turning_points-003` is
`fallback:review_rejected`, then `failed:review:ValueError`, then `failed:orchestrate:ValueError`,
then `failed:review:ValueError` across the series (companion, §3), and `aliases_typos-010` moves
from `fallback:review_rejected` to `failed:review:ValueError`. That is a size-dependent failure
moving between calls, not a reviewer rule.

What the user sees: HTTP 200, `warnings: ["Model or budget unavailable."]`, `degraded: true`,
`route: "factual_fallback"`, `llm_validated: false` (`analyst_loop.py:380-393`), and a banner saying
"Optional AI or search services are degraded"
(`apps/web/src/features/knicks/answer-panel.tsx:86-95`). Both statements are false: the provider was
reachable and the ledger reserved the turn. A retry re-enters the same path, and an operator would
chase a non-existent outage.

Reliability consequence: three failure classes collapse into one string — provider or transport
failure, ledger refusal, and an internal payload-contract bug. Only the first two are worth
retrying or alerting; the third is deterministic. Because `route` and `tool_calls` are excluded from
production responses (`apps/api/app/api/analysis_models.py:82-113`), a production operator cannot
tell them apart at all.

## 2. `date_range_last_n-007`: a correct claim was dropped by 16 bytes, and the reviewer certified the gap

Question: "What was their average margin over the last 8 games?" The label expects 7–1 with an
average margin of 9.75 (`docs/release-evidence/evaluation-label-drafts.jsonl:32`). The answer
declines: "… includes Knicks wins (7), losses (1), and points per game (110.25), but no margin
value."

`team()` always emits both `points_per_game` and `margin_per_game` when `aggregation="average"`
(`analyst_calculations.py:108-114`), so the claim existed and was in `loop.results`.
`build_payload` admits claims one group at a time and silently `continue`s when the projected
payload would exceed the limit (`analyst_provider.py:199-235`). Replaying that rule with the real
`VerifiedClaim`, `claim_view` and `token_upper_bound`:

```
base payload (Action schema, one team result)          4,072
+ wins                                                 4,601  admitted
+ losses                                               5,137  admitted
+ points_per_game                                      5,726  admitted
+ margin_per_game                                      6,311  > 6,295 limit → skipped
```

The fourth claim misses by 16 bytes; claim sizes are 545–594 bytes. That reproduces the delivered
text exactly: the model could see wins, losses and points per game, and no margin.

The damaging part is what happens next. "No margin value" is a coverage statement, so
`validate_review` requires no claim or evidence ids for it (`evidence_contracts.py:254-276`). The
reviewer only ever receives claims the writer was sent: `build_payload` selects
`loop.sent_claims[u.claim_id]` (`analyst_provider.py:165`) and `validate` builds `reviewable` from
`sent_claim`/`sent_evidence` only (`analyst_loop.py:256-262`); `validate_review` checks supporting
ids against that same map (`evidence_contracts.py:262-276`). Neither side can observe the omission,
so the whole-answer review certifies a false statement about archive coverage and the outcome is
`validated_declined`. The user sees a confident, undecorated refusal (`warnings: []`,
`degraded: false`, `llm_validated: true`) — the most trusted-looking output in this set. This is the
only row of the seven that declines an answerable question, and it is the one the review layer was
supposed to prevent.

The fix is not "more budget" alone: an answer built from a subset of the sibling team claims is
internally consistent, so the omission must be either impossible (admit the whole fact family) or
visible (tell the writer and the reviewer what was omitted, and fail closed if the answer's own
claims did not fit).

## 3. `exact_statistics-009` and `comparisons-002`: reviewer variance where the contract offers no comparison or extremum claim

Both rows end in `fallback:review_rejected`: the writer produced wording, review rejected it, the
single repair did not pass, and `render_fallback` delivered deterministic claims with the warning
"Proposed wording did not pass evidence review." (`analyst_loop.py:232`, `297-318`).

The run history is the decisive fact: `comparisons-002` failed with `failed:review:ValueError` in
`baseline` and `after-fix1`, was reviewer-accepted (`llm_validated: true`) in `after-fix2`,
`after-fix3` and `after-fix4`, then rejected in `final3`; `exact_statistics-009` was
reviewer-accepted in `after-fix4` and rejected in `final3` (companion, §3). The same question
therefore both passes and fails across runs, so neither a fixed reviewer rule nor a fixed writer
output explains `final3` on its own. The rejected wording is **not persisted** anywhere — not in the
JSONL, not in the API response, not in the trace — so the exact span, and with it the attribution
between reviewer strictness and a wording change, cannot be recovered. Two code-level mechanisms can
produce the rejection:

- **Zero-tolerance span reassembly.** `validate_review` rejects the entire review if the assertion
  texts do not concatenate exactly to the answer text (`evidence_contracts.py:260-261`); the prompt
  demands verbatim copying including trailing spaces (`analyst_provider.py:270-292`). One
  normalized space or punctuation mark rejects every assertion's verdict. This is a plausible source
  of run-to-run flips.
- **Evaluative wording with no supporting claim.** The writer prompt forbids rankings ("Do not
  infer causes or rankings", `analyst_provider.py:313-316`), and `VerifiedClaim` has no comparison
  or extremum variant (`evidence_contracts.py:29-75`); `team()` only aggregates a population
  (`analyst_calculations.py:94-139`), and `discover_facts` produces catalog extremes for player stat
  families (`analyst_discovery.py:124-266`), not "worst loss by margin". Any sentence that actually
  answers "as scorers" or "worst loss" asserts a comparison the claim set cannot carry, so the
  reviewer is right to reject it.

For `comparisons-002` the delivered fallback is the neutral side-by-side (two `player()` claims,
19.2 and 26.5 points per appearance): correct numbers, but not `meets_expectation`, because the
harness only accepts reviewer-validated text (`tools/release/analyst_live_e2e.py:81-85`).

For `exact_statistics-009` the gap is wider. The label expects a single game (`games: 1`,
`average_margin: -38.0`, `docs/release-evidence/evaluation-label-drafts.jsonl:9`), but "worst loss"
sets `game_result="L"` (`query_resolution.py:396-405`), so the tool's population is all 32 losses.
The delivered fallback is wins 0 / losses 32 / points 3421 over those 32 games: an aggregate that
cannot answer the question, with the only relevant number (the margin) cut by `claims[:3]`
(`analyst_loop.py:301`, HEAD). The first sentence a user reads is "Knicks wins: 0 over 32 archived
games", which is true of the loss subset and reads as nonsense.

Classification: reviewer strictness/variance, made possible by a contract that cannot express
comparisons or extrema. Not a budget failure, and not attributable to a single rule from the
available record.

## 4. `unsupported-006` and `unsupported-008`: the fallback answers instead of declining

Both questions are labelled unanswerable (`answerable: false`,
`docs/release-evidence/evaluation-label-drafts.jsonl:111,113`).

`unsupported-006` ("current Eastern Conference standings") was delivered as the 101-game record plus
"I don't have live injury or current-status updates." The sentence is appended only because
`re_search_live` matches the word "current" (`analyst_loop.py:311,396-399`); the claims are still
emitted. `unsupported-008` ("How will Brunson play next season?") was delivered as a single
current-season stat with **no disclaimer at all**, because `re_search_live`'s vocabulary is
`injur*|today|current|live|tonight` and misses "next season" / "will".

The structural cause is that after any review rejection the only path is `render_fallback`, which
always builds an answer from claims (`analyst_loop.py:297-318`) and always returns
`llm_validated: false`. There is no decline mode, so an unanswerable question that reaches the
fallback cannot produce a reviewer-validated refusal — and `meets_expectation` requires
`validated_declined` for unsupported rows (`tools/release/analyst_live_e2e.py:81-85`). Two further
gaps compound it:

- `fallback_claims` matches on subject, population and metric only (`analyst_fallback.py:23-91`);
  it never considers that the question asks about the future or asks for an extremum, so it cannot
  tell that its "relevant" claim is irrelevant.
- `render_fallback` output is never reviewer-validated: it is built and rendered directly, so the
  numbers are backend-verified but the sentence that frames them is not.

`unsupported-008` is the worst user-facing outcome in this set: a plausible-looking stat, no
disclaimer in the answer text, and the only signal is the review-failure warning plus the degraded
banner.

## 5. The ledger is not the cause (excluded)

`BudgetReservation.reserve` returns `None` for an exhausted ledger, a missing Redis, or a failed
eval (`analyst_budget.py:40-61`); it never raises for that case. When `reserve(3)` returns `None`,
`run` calls the fallback without an exception (`analyst_loop.py:127-131`), so no
`analyst_execution_failed` record exists and the harness classifies the row as `fallback:other`
(`tools/release/analyst_live_e2e.py:68-79`). A `failed:*` outcome therefore proves the model path
was entered and raised. Both `ValueError` rows reached the reviewer, so at least three reservations
had been accepted; the ledger was working.

The ledger docs also contradict the code (`analyst_budget.py:1-14` vs
`docs/analyst-evidence-loop.md`, "Budget operations"); the reliability design should reconcile them.

## 6. Where a fix would live (no code in this note)

1. **Make payload-budget failure a typed, non-retryable error, and stop calling it "model or budget
   unavailable."** `build_payload`/`request_model` (`analyst_provider.py:194-196, 226-231,
   341-349`) should raise a dedicated exception carrying the component sizes; `AnalystLoop.run`
   (`analyst_loop.py:129-151`) should map exception classes to distinct warnings and log the sizes;
   `render_fallback`'s reason should say the answer could not be assembled rather than blaming the
   provider. Addresses both `ValueError` rows.
2. **Stop silent claim truncation.** `build_payload` (`analyst_provider.py:199-235`) should admit or
   reject based on the answer's claims and the question's metric, treat the
   wins/losses/points/margin family as indivisible, and record what was omitted; either the writer
   is told the omission or the turn fails with a specific reason. Also decide what
   `analyst_input_tokens` means: today it is compared against UTF-8 bytes
   (`analyst_provider.py:34-37`), which is why 16 bytes decided `date_range_last_n-007`. Addresses
   that row and the repair overflow.
3. **Give the reviewer a way to see truncation.** Either pass the omitted claim ids to the reviewer
   or have `validate_review` check coverage assertions ("no margin value") against the claim
   registry instead of the writer's subset (`analyst_loop.py:256-263`,
   `evidence_contracts.py:254-276`).
4. **Add a decline path to the fallback and make claim relevance intent-aware.**
   `render_fallback` (`analyst_loop.py:297-318`) needs a refusal mode for unanswerable/future
   questions; `fallback_claims` (`analyst_fallback.py:23-91`) needs to consider the question's time
   frame and extremum/comparison intent; `re_search_live` (`analyst_loop.py:396-399`) needs the
   future-tense vocabulary. `claims[:3]` should be replaced by metric-aware selection, not a larger
   constant. Addresses both `unsupported` rows and improves every fallback text.
5. **Model comparison and extremum claims, or make the impossibility explicit.** Either
   `evidence_contracts` grows a comparison/extremum claim (two sources or a ranked population) with
   a matching assertion type, or the prompts stop forbidding the only wording that answers these
   questions and the writer is told to decline with the coverage reason. Addresses
   `comparisons-002` and `exact_statistics-009`, and would make their outcomes stable.
6. **Review robustness.** Either accept a returned review whose spans match the answer after
   whitespace normalization, or repair span boundaries explicitly instead of rejecting the whole
   answer on one character (`evidence_contracts.py:260-261`). If zero tolerance is kept, say so in
   the repair hint (`analyst_loop.py:262-263`).
7. **Repair-hint budget.** Cap or compress `encoded(review.model_dump())` before it becomes the next
   payload's `repair` string (`analyst_loop.py:262-263`); send offending spans and reasons only.
8. **Evidence and telemetry.** `analyst_live_e2e.classify` (`tools/release/analyst_live_e2e.py:68-79`)
   should consume structured failure data instead of warning substrings; the API response should
   carry an operator-visible failure code in production (`apps/api/app/api/analysis_models.py:82-113`);
   persisted turns should keep the rejected wording or a hash of it.
