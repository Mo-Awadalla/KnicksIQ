# Scoring the llm_primary analyst, 2026-10-21

Replaces the phrase-match screen with checks that make the release number difficult to earn.
Branch `codex/llm-scoring`, worktree `scoring`, Redis db 2, release `2025-26.20260928.1`.

## How the old screen could be fooled

| Fooling mode | New check |
| --- | --- |
| A refusal phrased unusually | Structure first: `refused`, `degraded`, warning fallback, then the phrase regex. Every fired signal is recorded. |
| A number from a different game or metric | Every number in a factual sentence must appear in a cited claim value or receipt. Offline reduced artifacts use a question-scoped archive index and are labelled weaker. |
| A hedged causal answer | `hedged_causal`: hedge plus causal or predictive language. |
| A decline that still states a fact | Numbers and entities in non-coverage sentences of a decline are checked too. |
| An answer that echoes the question | `echo_question`: high question-token overlap with no new numbers or entities. |
| A clarification counted as an answer | `structure:clarification`; trailing questions and "which game do you mean" patterns fail answerable questions. |
| A comparison with the wrong metric or subject | Scoped values use only the question's games, players and metric; named entities must be in scope. |
| A requirement that was skipped | `required_facts`, `required_entities`, `required_phrases`; turning-point answers need a quarter, period, run or date. |

## Decline detection

The public contract exposes `refused`, `degraded`, `llm_validated`, `warnings`, `route` and
`citations`. `refused` is only set by the deterministic pre-check; the llm_primary path never
sets it, and the review's `assertion_type` (`coverage`, `conversational`) is not in the public
payload. The scorer therefore records `field:refused`, `field:degraded`, `field:warning_fallback`
and `field:unvalidated` when present, then `structure:clarification`, and only then
`phrase:decline`. This is why a structural `declined` field is a contract recommendation, not a
working signal today.

## Backing modes

- `claims`: a number or entity appears in `citations[].metadata.claim` (value, statement,
  denominator, sample size, window, filters) or in a cited receipt. This is the strong mode.
- `archive_index_scoped`: the committed artifact has citation counts but no claim values. Values
  are checked against the games, players and metric named by the question. It is stronger than a
  global index and still weaker than claim proof.
- `archive_index`: no question scope could be derived; global release values only.

`unbacked_numbers` and `unbacked_entities` are per response. `claim_backed_meets_expectation`
requires cited claims and is reported separately.

## Held-out set

`apps/api/app/evaluation/heldout_questions.jsonl`: 60 questions, 9 exact statistics, 9 date
ranges, 8 comparisons, 8 aliases and typos, 8 single-game narratives, 8 turning points, 10
unsupported. No follow-ups. `expected_route`, `answerable`, `required_facts`,
`required_entities`, `required_phrases` and `filters` are emitted by
`app/evaluation/build_heldout_set.py` from the active release. No model labels. The set uses
games and players that `questions.jsonl` does not: MIA, CLE, PHI, SAS, DET, MIL, DEN, LAL, OKC;
Robinson, McBride, Shamet, Clarkson, Hukporti. `heldout_questions.meta.json` carries the tuning
policy: nobody may tune against individual items, only through this scorer's report.

## Results

### 70-question committed responses, offline (no live spend)

Source: `docs/release-evidence/llm-primary-20261018/final3-n70.responses.jsonl`. That artifact
keeps only a citation count, so the strong mode is unavailable: zero answerable passes can be
claim-proven. The scoped archive fallback is the best available check.

| Category | Questions | Old | New |
| --- | --- | --- | --- |
| exact_statistics | 10 | 9 | 7 |
| date_range_last_n | 10 | 9 | 4 |
| aliases_typos | 10 | 6 | 5 |
| unsupported | 10 | 5 | 5 |
| turning_points | 10 | 4 | 0 |
| comparisons | 10 | 2 | 0 |
| single_game_narrative | 10 | 2 | 0 |
| Total | 70 | 37 | 21 |

`Old` is the pre-existing `meets_expectation`. `New` is this scorer. `Claim-backed` is 5/70:
the five unsupported declines. Answerable claim-backed is 0/32 because the artifact has no
claim values.

### How the 37 became 21

16 old passes do not survive:

- 12 are clarifications counted as answers: date_range 005, 008, 009, 010; comparisons 004;
  narrative 007, 009; turning 002, 004, 006, 010; aliases 003. That is skipped work, not a
  wrong number.
- 3 have numbers that the question scope does not support: date_range 006 says "5 wins, 0
  losses across 5 away games" in December, but the release has 5-3 in 8 away games;
  comparisons 008 says Towns 11.6 rebounds over 94 appearances and Hart 7.7 over 85, but the
  release has 11.35 over 96 and 7.75 over 87; exact_statistics 008 adds "0 losses in that
  filtered set" to an otherwise correct 54-point win.
- 1 answers a different subject: exact_statistics 010 asks for the team's highest-scoring game
  and gets the highest individual scoring game.

The 21 survivors were spot-checked against the release; all match. The honest baseline is
therefore 21/37, of which only the 5 unsupported declines are claim-backed. 37 was a screen:
12 passes were questions the model asked back, and 4 were substantively wrong or off-subject.

### Held-out baseline, 60 live questions

Run once against the real provider on the restored release, then re-scored offline from the
captured payloads so every row uses the same checks. 23 rows that ended in a transient provider
or reviewer failure were re-run once; the reruns replaced the failed rows.

| Category | Questions | Old | New |
| --- | --- | --- | --- |
| exact_statistics | 9 | 2 | 2 |
| date_range_last_n | 9 | 1 | 1 |
| single_game_narrative | 8 | 1 | 1 |
| aliases_typos | 8 | 0 | 0 |
| comparisons | 8 | 0 | 0 |
| turning_points | 8 | 1 | 0 |
| unsupported | 10 | 1 | 1 |
| Total | 60 | 6 | 5 |

The held-out baseline of the current code is 5/60 (8.3%, Wilson 95% interval 3.6% to 18.1%).
The new checks removed one old pass and added none.

Why the number is low:

- 45 of 60 responses ended in `fallback:review_rejected`: the reviewer rejected the model's
  wording and the fallback path returned aggregate stats. These fail validated delivery. That is
  the fallback aggregate dump owned by CorrectnessFix.
- 8 responses still ended in `failed:revise:*` or `failed:orchestrate:*` after one rerun. They
  are counted as misses, not retried again.
- 9 of the 10 unsupported questions fell back to a factual dump (69 wins, 32 losses, 11,750
  points). One, "how many points will Brunson score tomorrow?", produced a validated decline
  and passed. The deterministic `refused` pre-check never runs in llm_primary.
- The 5 passes are four validated answers (regular-season record, home losses, March record,
  the December 21 Miami narrative) plus the validated unsupported decline. All numbers,
  entities, required facts and phrases matched.
- The lost old pass was a validated answer that asked which quarter was meant. That is skipped
  work, not a wrong fact.

Live budget: 84 questions (60 baseline, 1 rerun of a RuntimeError row, 23 reruns of failed
rows). Monthly ledger after the run: $1.15 of the $2 cutoff.

This is a baseline, not a quality target. It measures today's code, including coverage gaps,
reviewer rejections, provider failures and fallback behaviour.

## Limitations

- The committed 70 artifact cannot support claim-level proof. Re-collect responses with full
  citations before quoting a strict 70 number.
- The reviewer is stochastic on today's provider. The held-out number is one trial per question;
  a proportion from 60 questions has a wide interval, and category cells are small.
- Held-out questions are answerable from the release, not necessarily from today's tools. They
  measure the current code, including its coverage gaps.

## Commands

From the `scoring` worktree after `uv sync --package knicksiq-api`:

```bash
# Regenerate the held-out set from the active release
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
.venv/bin/python -m app.evaluation.build_heldout_set

# Re-score the committed 70 responses offline
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
.venv/bin/python tools/release/analyst_live_e2e.py \
  --responses docs/release-evidence/llm-primary-20261018/final3-n70.responses.jsonl \
  --out docs/release-evidence/llm-primary-20261021/scoring/baseline-70.rescored.json

# Run the held-out set live (60 questions, own Redis db)
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
REDIS_URL=redis://localhost:56500/2 RAG_QDRANT_ENABLED=false \
ANALYSIS_ANSWER_MODE=llm_primary ANALYST_EVIDENCE_LOOP_ENABLED=true \
OPENROUTER_MONTHLY_CUTOFF_USD=2 AI_PROVIDER=openrouter \
AI_BASE_URL=https://openrouter.ai/api/v1 AI_CHAT_MODEL=deepseek/deepseek-v4.1-flash \
AI_API_KEY=<from .env> OPENROUTER_API_KEY=<from .env> \
.venv/bin/python tools/release/analyst_live_e2e.py --heldout --all \
  --out docs/release-evidence/llm-primary-20261021/scoring/heldout-60.json
```

## Files

- `tools/release/analyst_live_e2e.py`: live and offline runner, category table, JSONL output.
- `tools/release/analyst_scoring.py`: scoring decision.
- `tools/release/analyst_checks.py`: tokens, claims, entities, decline signals.
- `tools/release/archive_values.py`: global and question-scoped archive indexes.
- `tools/release/team_aliases.py`: team and player aliases used by the indexes.
- `apps/api/app/evaluation/build_heldout_set.py`, `heldout_cases.py`, `heldout_facts.py`:
  deterministic generation of the held-out set.
- `heldout_questions.jsonl`, `heldout_questions.meta.json`: the set and its policy.
- `baseline-70.rescored.json`, `baseline-70.scored.jsonl`: the 70 offline baseline and per
  question checks.
- `heldout-60.json`, `heldout-60.responses.jsonl`, `heldout-60.scored.jsonl`: the live baseline.
