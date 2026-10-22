# Reviewer citations: supported verdict with empty ids

Branch `codex/llm-w3-revids`, worktree `w3-revids`, base `codex/llmp-integration` at `5b585e6`.

Observed defect: the reviewer returns `verdict: supported` for a factual span and leaves
`supporting_claim_ids` and `supporting_evidence_ids` empty (`"[]"`), so `validate_review` fails
closed and the user gets the deterministic fallback instead of the reviewed answer. Example from
the ticket: "In the 2025-26 regular season, the Knicks went 53-29 over 82 archived games."

## Measurement

No new live questions were spent after the OpenRouter account returned HTTP 402
(`in_flight_budget_exhausted`). Every 402 result was discarded, including a review call that
failed with 402 and turned into a fallback. What remains is:

- `base-live-valid.jsonl`: 12 valid turns of the intended 20 question x 2 trial base arm, real
  provider, local release `2025-26.20260928.1`, Redis db 2. The other 8 turns failed with 402.
- 57 recorded review calls that carry at least one factual or interpretation span (69 calls
  total) from `reviewer/head-units.jsonl`, `reviewer/head-production-24.jsonl`,
  `reviewer/base-production-8.jsonl`, `reviewer/head-fix-*.jsonl`, `example-review-supported.jsonl`
  and the 12 valid base turns.

Correlation (`correlation-recorded.json`, produced by `probe.py correlate`):

| Dimension | Bucket | Calls | Calls with supported factual span and both id lists empty |
| --- | --- | ---: | ---: |
| Provider | Together | 57 | 0 |
| Payload bytes | <= 5000 | 22 | 0 |
| Payload bytes | <= 8000 | 25 | 0 |
| Payload bytes | <= 11000 | 10 | 0 |
| Claims in payload | <= 1 | 27 | 0 |
| Claims in payload | <= 2 | 16 | 0 |
| Claims in payload | <= 3 | 7 | 0 |
| Claims in payload | > 3 | 7 | 0 |
| Review spans | 1 | 48 | 0 |
| Review spans | 2 | 7 | 0 |
| Review spans | 3 | 2 | 0 |
| Prompt wording | integration prompt only | 57 | 0 |

Observed ranges: payload 3,508 to 10,869 bytes, claims 0 to 8, spans 1 to 3.

Findings:

1. The provider hypothesis is UNTESTED, not refuted. Every recorded successful call was served
   by `Together`, so the sample has no provider contrast. The 15/21 run that motivated this task
   did not record the raw verdict or the upstream provider; only the generic fallback warning
   survived. Payload size, claim count and span count show no event in this sample either.
2. The defect did not reproduce in the 57 recorded calls or in the 12 valid base turns. The
   reported 0/14 to 15/21 swing cannot be attributed from the surviving data.
3. Because routing is outside this branch and the cause is unmeasured, the fix does not depend on
   provider behaviour. It makes the citation requirement unambiguous and repairs the one class of
   dropped citation that can be reconstructed deterministically.

## Fix

`reviewer_system_prompt()` (`apps/api/app/services/analyst_provider.py`)

The citation rule is now explicit and placed before the coverage/conversational exception: a
factual or interpretation span MUST return at least one id copied exactly from
`claims[].claim_id` or `evidence[].evidence_id`; empty lists are invalid for those types; if the
reviewer cannot cite, it must return `insufficient_evidence` instead of `supported`. Prompt size
1957 to 1960 bytes.

`deterministic_claim_ids()` and `validate_review()` (`apps/api/app/services/evidence_contracts.py`)

When a supported factual or interpretation span arrives with both citing arrays empty, the gate
attaches claim ids only if all of the following hold:

- every number in the span is a supplied claim value or claim field, using the deterministic
  gate's rounding and percent tolerance. A number that is unknown, or that only a receipt or
  capability explains, blocks the repair;
- each stated value matches exactly one claim that the answer declared. A value equal to two
  declared claims is ambiguous and stays uncited;
- at least one value is attributed; a span with no numeric value stays uncited;
- the verdict is supported (an unsupported or insufficient verdict is never repaired).

Why this is not a weakening:

- A supported span that was rejected for no backing at all still fails closed: non-numeric spans
  and spans whose numbers are not claim-backed get no ids and the answer falls back.
- Every attached id is a real backend claim with its own receipt; the span has more backing
  after the repair, not less. The reviewer's supported verdict still carries the subject, metric,
  unit and scope judgment, which the backend does not redo.
- The old empty-id rejection was an accidental citation-presence check, not a correctness check.
  A reviewer that supplied the id for the same verdict was already accepted before this change.
  The mutation check below shows no wrong number becomes accepted.

`AnalystLoop.validate()` (`apps/api/app/services/analyst_loop.py`)

Every review call now writes `review_spans`, `review_empty_id_spans`,
`review_attachable_spans` and `review_accepted` into the existing per-call trace entry, which the
API returns as `tool_calls`. Rejections also log `analyst_review_rejected` with provider,
finish reason and the same counts. The next occurrence of the defect will therefore carry the
provider and verdict shape that the 15/21 run lost. No answer text or claim text is logged.

## Offline before/after

### End to end with a scripted provider (`e2e-old.json`, `e2e-new.json`)

`empty_ids_e2e.py` runs the in-process app against the local restored release. A scripted adapter
answers with one real claim and returns the exact malformed review: every span supported, both id
lists empty. `--policy old` uses the `5b585e6` validation rule.

| Case | Old policy | New policy |
| --- | --- | --- |
| Backed span (declared claim value) | fallback, `llm_validated: false` | delivered, `llm_validated: true` |
| Unbacked span (no numbers, no claim) | fallback | fallback |

The delivered case is the ticket answer shape ("Knicks regular season wins: 53 over 82 archived
games."). The unbacked case proves the fail-closed behaviour is unchanged.

### Recorded verdicts with ids blanked (`empty-ids-offline.json`)

The recorded reviewer verdicts are replayed through the old and new validation rules after
clearing both citing arrays on factual and interpretation spans.

| Label | Units | Old accepts | New accepts | Recovered |
| --- | ---: | ---: | ---: | ---: |
| Correct | 14 | 1 | 13 | 12 |
| Wrong | 3 | 0 | 1 | 1 |

`date_range_last_n-004` still fails closed: its span contains the question's date criteria
("January 1 through January 31"), which are not claim values. `date_range_last_n-006` is the one
wrong unit recovered; see open risks.

### Deterministic gate and mutations

`analyst_gate_mutations.py` on the 14 labeled-correct units (the ticket said 13; the recorded
labels contain 14 with numeric mutations), 288 wrong mutations and 13 ratio controls:

| Run | Wrong accepted | Controls |
| --- | ---: | ---: |
| Committed `reviewer/gate-mutations-after.json` | 1 / 288 | 13 / 13 accepted |
| This branch (`gate-mutations-revids.json`) | 1 / 288 | 13 / 13 accepted |

The gate is unchanged. The one accepted wrong mutation is the documented percent-of-ratio case.

The new acceptance path was also checked with the worst possible reviewer: every span supported
with both id lists empty. Of the 288 wrong mutations, 1 already passes the deterministic gate and
the backfill attaches nothing for it; `new_blank_accepted` is 0 / 288. All 13 correct ratio
controls also stay uncited under this simulation because the added ratio claim is not declared by
the writer, so that path is conservative rather than a false accept.

## Files changed

- `apps/api/app/services/analyst_provider.py`: reviewer citation rule.
- `apps/api/app/services/evidence_contracts.py`: `deterministic_claim_ids`, attachment in
  `validate_review`.
- `apps/api/app/services/analyst_loop.py`: trace diagnostics and rejection log.
- `.gitattributes`: generated JSON/JSONL markers for this directory.
- This directory: `probe.py`, `evaluate_empty_ids.py`, `empty_ids_e2e.py`, and the JSON/JSONL
  outputs named above.

## Pending live runs (blocked on OpenRouter credits)

All runs use the wave 3 settings and Redis db 2. The base arm must run on `5b585e6`.

    # Base arm, 20 questions x 2 trials plus retries (create a base worktree first):
    git worktree add ~/.local/share/knicksiq/worktrees/w3-revids-base \
      -b codex/llm-w3-revids-base 5b585e6
    cd ~/.local/share/knicksiq/worktrees/w3-revids-base && uv sync --all-packages --all-extras --dev
    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    REDIS_URL=redis://localhost:56500/2 OPENROUTER_MONTHLY_CUTOFF_USD=2 \
    ANALYSIS_ANSWER_MODE=llm_primary ANALYST_EVIDENCE_LOOP_ENABLED=true RAG_QDRANT_ENABLED=false \
    AI_REASONING_EFFORT=none \
    uv run --package knicksiq-api python \
      ~/.local/share/knicksiq/worktrees/w3-revids/docs/release-evidence/llm-primary-20261021/revids/probe.py \
      live --trials 2 --tag base --out <revids>/base-live.jsonl

    # After arm, same command in the w3-revids worktree with --tag after --out <revids>/after-live.jsonl

    # Grow the review-call sample without the writer (records provider and raw verdicts):
    ... probe.py replay --records <revids>/base-live.jsonl --trials 3 --out <revids>/base-replay.jsonl
    ... probe.py replay --records <revids>/after-live.jsonl --trials 3 --out <revids>/after-replay.jsonl

    # Correlation table and before/after rate:
    ... probe.py correlate --records <revids>/base-live.jsonl <revids>/base-replay.jsonl \
      <revids>/after-live.jsonl <revids>/after-replay.jsonl --out <revids>/correlation-live.json

    # Live replay controls on the recorded units (current prompt, base and head modes):
    DB_URL=... REDIS_URL=... uv run --package knicksiq-api python \
      tools/release/analyst_review_replay.py \
      --records docs/release-evidence/llm-primary-20261021/reviewer/head-units.jsonl \
      --labels docs/release-evidence/llm-primary-20261021/reviewer/labels.json \
      --trials 3 --out <revids>/replay-controls.json

    # Mutation controls with the model reviewer (not the offline gate):
    ... analyst_review_replay.py --records .../head-units.jsonl --labels .../labels.json \
      --mutations-only --out <revids>/mutations-live.json

Credits ran out before the base arm could finish its 20 questions, so no before/after live rate
exists yet. The acceptance items "before/after rate over 20 questions x 2 trials" and "live
replay controls" are NOT VERIFIED.

## Open risks

1. The provider correlation is unmeasured: 57 recorded calls came from one upstream provider.
   After credits return, `probe.py replay` varies the call time and records the provider, which
   is the intended test.
2. `date_range_last_n-006` is a wrong answer built from wrong claims (December road record 5-0
   over 5 instead of 5-3 over 8; the filter shrank the denominator). Under a blank-id review the
   backfill accepts it, where the old rule rejected it for missing ids. The same answer is
   accepted by the old rule when the reviewer cites the claims, which it did in the recording.
   The underlying defect is claim construction, not citations. The mutation check shows no wrong
   number is newly accepted.
3. A correct answer whose only numeric context is question-derived date criteria
   (`date_range_last_n-004`) still falls back if the reviewer drops the citation. That is the
   deliberate conservative edge of the attachment rule.
4. The prompt change is not yet measured live. It is the only path that helps non-numeric
   factual spans, which the deterministic repair cannot cover.
