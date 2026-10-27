# Reviewer stability: diagnosis, fix and offline replay

Branch `codex/llmp-reviewer`, based on `codex/llmp-integration`. The reviewer work was
developed on `254fdc9` and merged with the advanced integration branch (honest scorer,
`decline` action, web changes) in `55286f5`. The reviewer prompt, deterministic gate and
replay are unchanged by that merge; the writer gained the decline/explain actions.
Worktree `~/.local/share/knicksiq/worktrees/reviewer`.

## What was measured

All runs used the local restored release `2025-26.20260928.1`, Redis db 11, the real
provider, `OPENROUTER_MONTHLY_CUTOFF_USD=2`. The production reasoning setting is
`AI_REASONING_EFFORT=none`; the first diagnostic runs accidentally omitted it. That
difference dominated the initial results and is reported separately rather than
hidden.

### Diagnostic runs without `AI_REASONING_EFFORT=none` (invalid as a production base)

29 questions, 0 and 1 validated per batch. Review attempts: 13 malformed or truncated
JSON responses, 25 provider `omitted message content` errors, 4 structure rejections.
The raw responses are reasoning prose followed by partial JSON, or a prose-only
response. This is an environment setting defect in the smoke harness, not a reviewer
prompt defect. `diagnostic-reasoning-default-exact-12.jsonl` and
`diagnostic-reasoning-default-mixed-17.jsonl` preserve it.

### Production settings (`AI_REASONING_EFFORT=none`)

- Base code (`codex/llmp-integration`): `base-production-8.jsonl`, 8 questions,
  8 validated, 0 reviewer rejections.
- Fixed head: `head-units.jsonl` merges 24 questions. First live pass produced
  19 validated and 5 `fallback:review_rejected`. Four of the five were the fixed
  defects below (one packing abort, three deterministic false rejects) and were
  rerun green. The fifth is a correct rejection of an answer that did not answer the
  question (`date_range_last_n-008`). Net live result after fixes: 23 validated,
  1 true rejection of a wrong answer, 0 false rejections.

## Root causes found

1. Reviewer responses can be reasoning prose or truncated JSON. Base validation
   parsed once and repaired; a repair that also failed dropped the answer. Fixed by
   one malformed-JSON retry plus a shorter, lower-verbosity reviewer prompt.
2. `validate_structure` required `displayed_value == round(value, places)` whenever
   `decimal_places` was set. A writer that sent the exact backend value with a
   display precision was rejected even though the value was correct. The exact
   backend value is now always accepted; a rounded value is also accepted.
3. Review payload packing raised `Full referenced claims cannot fit reviewer input`
   for a four-claim answer. Reviewer claim views now drop eligibility policy and
   generic coverage caveats (the semantic fields, value, scope, window and receipts
   remain), so review proceeds.
4. Span identity was exact-text equality. Paraphrased or whitespace-normalised
   echoes failed. The backend now owns spans and requires one verdict per span in
   order; the echoed text is not an alignment key.
5. A supported verdict with a stale `offending_text` was rejected. Supported is
   authoritative; the field is ignored for supported spans.
6. The reviewer cited backend baseline claims the writer did not repeat in
   `answer.claims`; that rejected correct answers. Any backend-issued sent claim may
   support a span; invented ids still fail closed.
7. Numbers were judged only by the model. The deterministic gate now requires every
   number in the answer to match a supplied claim value within rounding tolerance, a
   receipt or a curated capability number. Identifier hashes and game ids are never
   whitelisted. Numbers from the question are allowed only in decline, coverage,
   date-window or clarification spans where they are criteria, not asserted facts.

## Offline replay

`tools/release/analyst_review_replay.py` replays recorded reviewer calls without the
writer. Base mode uses the frozen base prompt and base validation; head mode uses the
current deterministic gate and reviewer. Three trials per answer, 17 labeled units
(14 correct, 3 wrong; missed-answer declines are excluded from the rates and listed
in `labels.json`).

| Set | Mode | Rejected / observations | Rate |
| --- | --- | ---: | ---: |
| Correct answers | base | 5 / 42 | 11.9% |
| Correct answers | head | 0 / 42 | 0.0% |
| Wrong answers | base | 4 / 9 | 44.4% |
| Wrong answers | head | 3 / 9 | 33.3% |

Base correct rejections: `comparisons-002` structure-rejected on all 3 trials
(exact value plus decimal_places), and `date_range_last_n-004` rejected by model
verdict on 2 of 3 trials. Head accepted every correct unit on every trial.

Wrong-answer detail: `date_range_last_n-008` is rejected 3/3 by both modes.
`exact_statistics-010` (answers the player scoring high instead of the team high)
is accepted 3/3 by head and 2/3 by base. That is a residual reviewer judgment miss,
not a number-provenance failure: the numbers are true, the subject is the wrong
aspect of the question. `date_range_last_n-006` is also accepted; its 5-0/5-game
denominator is a tool scope bug owned by CorrectnessFix.

### Mutated wrong numbers

Each unit contributes a text-number swap (a number in the answer changed at the
span's precision to a value absent from all trusted records) and, where the declared
answer carries a numeric claim, a claim-value mutation. Two trials per mutation,
64 observations per mode.

| Mode | Wrong-number acceptances / observations |
| --- | ---: |
| base | 2 / 64 |
| head | 0 / 64 |

Base accepted `7.94 -> 7.95` twice (the true value 7.9406 is 0.0094 away, outside the
0.005 rounding tolerance). Head rejected every mutated number deterministically
before any reviewer call. `mutations.json` reports
`zero_head_acceptances: true`.

Correction, 2026-10-22: head 0/64 is a selection-biased deterministic regression result.
Text swaps were chosen only when the gate rejects them, and claim-value changes fail the
structure check, so no head observation reached the model reviewer. It is not a reviewer
false-acceptance rate; that rate is unmeasured. See `gate-mutations.md`.

## Files changed

- `apps/api/app/services/analyst_review_checks.py` (new): span coverage criteria,
  numeric provenance, rounding tolerance, identifier filtering, structure checks.
- `apps/api/app/services/evidence_contracts.py`: `split_review_spans`,
  `claim_value_issues`, positional `validate_review`, exact-or-rounded claim values,
  prompt/validator version bump.
- `apps/api/app/services/analyst_loop.py`: deterministic gate before the reviewer,
  one malformed-review retry.
- `apps/api/app/services/analyst_provider.py`: reviewer prompt, shared span splitter,
  compact review claim view.
- `docs/analyst-evidence-loop.md`: review contract updated.
- `tools/release/analyst_review_record.py` (new): records reviewer payloads,
  responses, verdicts and validation outcomes from the live path.
- `tools/release/analyst_review_replay.py` (new): base/head replay and mutation set.
- `tools/release/analyst_review_base.py` (new): frozen base reviewer contract for replay.
- `apps/api/app/tests/support/analyst_protocol.py` and
  `apps/api/app/tests/test_analyst_refusal.py`: fixtures return one review item per
  backend span, matching the reviewer contract.

## Gate

After merging `codex/llmp-integration`:

- `TEST_MODE=true uv run pytest apps packages tools/report_audit`: 417 passed.
- `uv run ruff check apps packages migrations`: all checks passed.
- `uv run ruff format --check apps packages migrations`: 230 files formatted.
- `uv run pyright apps packages migrations`: 0 errors.

## Commands

```sh
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
REDIS_URL=redis://localhost:56500/11 AI_REASONING_EFFORT=none \
OPENROUTER_MONTHLY_CUTOFF_USD=2 \
uv run --package knicksiq-api python tools/release/analyst_review_record.py \
  --ids ... --out docs/release-evidence/llm-primary-20261021/reviewer/head-units.jsonl

AI_REASONING_EFFORT=none OPENROUTER_MONTHLY_CUTOFF_USD=2 \
uv run --package knicksiq-api python tools/release/analyst_review_replay.py \
  --records docs/release-evidence/llm-primary-20261021/reviewer/head-units.jsonl \
  --labels docs/release-evidence/llm-primary-20261021/reviewer/labels.json \
  --trials 3 --mutations \
  --out docs/release-evidence/llm-primary-20261021/reviewer/replay.json

uv run ruff check apps packages migrations
uv run ruff format --check apps packages migrations
uv run pyright apps packages migrations
TEST_MODE=true uv run pytest apps packages tools/report_audit
```

Live spend: 79 question posts (75 with provider calls; four aborted before any model
call from a harness TypeError that was fixed). Replay reviewer calls cost
$0.057 for the rate run plus the mutation run; the provider ledger is db 11.

## Open risks

- Reviewer judgment on natural wrong answers is not perfect
  (`exact_statistics-010`), though every mutated number is rejected.
- Missed-answer declines and tool-gap answers are excluded from the labeled rates
  because the reviewer cannot see data the tools did not retrieve; CorrectnessFix
  owns those surfaces.
- Labels were checked against independent SQL in this artifact, not by a second
  human. Held-out reviewer calibration remains owner-gated.
- The no-reasoning diagnostic is retained as evidence of an environment defect; a
  smoke harness that omits `AI_REASONING_EFFORT=none` will look like a reviewer
  failure.

Correction, 2026-10-22: `analyst_review_replay.call_reviewer` defaulted to 1,200 output tokens
while the deployed reviewer uses `analyst_review_max_tokens` (3,000). The replay rates above
(false rejects 5/42 to 0/42) were therefore measured on a reviewer capped at 1,200 tokens.
The default now follows the production setting (`80a6d1b`); rerun the replay to restate them.
