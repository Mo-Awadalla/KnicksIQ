# Held-out v2 analyst evaluation set

Fresh held-out set for the `ANALYSIS_ANSWER_MODE=llm_primary` release gate. It replaces the
60-question set whose rows were rescored after tuning. This set has not been run against the
analyst. No live provider call was made while authoring, generating or checking it.

## What is in it

- 80 answerable and unsupported questions across the seven scored categories.
- 10 two-turn follow-up sessions (20 turns). Turn one is context; turn two is the scored
  follow-up.
- Every expected fact is computed from the active local release by the generator. No model
  labels, no hand-entered numbers.

| Category | Count |
| --- | ---: |
| exact_statistics | 12 |
| date_range_last_n | 12 |
| comparisons | 11 |
| single_game_narrative | 11 |
| turning_points | 11 |
| aliases_typos | 11 |
| unsupported | 12 |
| follow-up sessions | 10 |

## Files

- `apps/api/app/evaluation/heldout_v2/build.py`: generator.
- `apps/api/app/evaluation/heldout_v2/cases.py`: exact, date, comparison and helper cases.
- `apps/api/app/evaluation/heldout_v2/cases_games.py`: narrative, turning-point and alias cases.
- `apps/api/app/evaluation/heldout_v2/follow_ups.py`: ten two-turn sessions.
- `apps/api/app/evaluation/heldout_v2/unsupported.py`: twelve unsupported asks.
- `apps/api/app/evaluation/heldout_v2/questions.jsonl`: 80 scored questions.
- `apps/api/app/evaluation/heldout_v2/follow_ups.jsonl`: 10 scored sessions.
- `apps/api/app/evaluation/heldout_v2/meta.json`: counts, phase policy, hashes, creation commit.
- `apps/api/app/evaluation/heldout_v2/overlap_report.json`: mechanical overlap report.

## Generation

The only input is the restored local release `2025-26.20260928.1`:

```bash
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicksiq-api python -m app.evaluation.heldout_v2.build
```

The committed files are deterministic. Verify without writing:

```bash
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicksiq-api python -m app.evaluation.heldout_v2.build --check
```

To rewrite the generated files byte-for-byte, pass the recorded commit:

```bash
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicksiq-api python -m app.evaluation.heldout_v2.build \
  --creation-commit c419fe3d751469beeff472a1cdb7343106334775 \
  --set-commit ad0d40e88f5212d2611f15203668da19b3f5d004
```

`meta.json` records `computed_from`, `question_order_sha256`,
`follow_up_order_sha256`, `combined_order_sha256`, the creation commit and the set commit. The
creation commit first added the set; the set commit has the exact questions and follow-up bytes
recorded here. The generator pins the question-order hashes, so changing a question text or its
order is a deliberate code edit.

Hashes at creation:

- `question_order_sha256`: `897c693f9c978cfe2f68a05136cda75d4d74e37c3640bd352c0196f76d3ed9bd`
- `follow_up_order_sha256`: `4d540490faec3944430871bb37024a5ef4f935205fe4f2b214a19df423601448`
- `combined_order_sha256`: `a5dff7e0b3ae3b042115b3b2a83481a3dc0d2ceaedbc2d958894bccc980142be`
- `creation_commit`: `c419fe3d751469beeff472a1cdb7343106334775`.
- `set_commit`: `ad0d40e88f5212d2611f15203668da19b3f5d004`.

## Season-phase policy

The shared policy is imported from `app/evaluation/heldout_phase.py`. Season-level questions use
the regular season. A question naming playoffs, overall or all phases uses that phase. A question
naming an opponent spans every phase unless it also names a phase. A date window uses the named
dates; a relative window spans every phase. A specific game is that game. Player averages count
only appearances with minutes greater than zero. Follow-up turns inherit the game established in
their session context. Team nicknames are canonicalised before the shared policy runs; the policy
rules themselves are unchanged.

## Coverage and overlap

The set is disjoint from `questions.jsonl` and `heldout_questions.jsonl` at the entity level:

- Game ids: zero overlap. New game-specific questions use games 9, 14, 15, 22, 25, 29, 32, 37,
  39, 40, 42, 43, 44, 50, 54, 57, 67, 68, 71 and 77. The old held-out set used 28, 49, 52, 59,
  60, 64, 92, 96 and 101.
- Players: zero overlap. The new set asks about Guerschon Yabusele, Jose Alvarado, Tyler Kolek,
  Pacôme Dadiet, Mohamed Diawara, Jeremy Sochan, Kevin McCullar Jr. and Trey Jemison III.
  The existing sets ask about Jalen Brunson, Karl-Anthony Towns, Mikal Bridges,
  Josh Hart, OG Anunoby, Mitchell Robinson, Landry Shamet, Miles McBride, Jordan Clarkson and
  Ariel Hukporti.
- Opponents: zero overlap. New opponent labels are Brooklyn, Dallas, Houston, Indiana, LA
  Clippers, Memphis, Minnesota, New Orleans, Orlando, Phoenix, Portland, Sacramento, Utah and
  Washington. The existing sets name Atlanta, Boston, Charlotte, Chicago, Cleveland, Denver,
  Detroit, Lakers, Miami, Milwaukee, Oklahoma City, Philadelphia, San Antonio and Toronto.
- Month-scoped questions: zero overlap. New questions scope October 2025 and April 2026. The old
  held-out set scoped November, January, February and March; the public set used December,
  January, February and March.
- Question text: zero normalized exact matches, no pair at or above 0.8 token Jaccard, maximum
  0.6667. The report lists ids and similarity only, never held-out text.

Some game-specific questions necessarily mention November, December, January, February or March
because that is when the games were played. Those are different dates and different games from
the existing sets; the month labels are not reused as scoped windows.

Re-run the mechanical check:

```bash
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicksiq-api python -m app.evaluation.heldout_v2.overlap
```

## Tuning embargo

This set is frozen. Nobody tunes prompts, tools, thresholds, routing, labels, retrieval settings
or code against individual rows. Do not copy a question, expected fact or failure into a prompt,
unit test, fixture or example. Do not use it to choose a fix.

Permitted use: one release run on the final candidate, then the aggregate scorer report and its
per-question check output for audit. If a row is wrong, record the defect and author a new set;
do not edit this set after seeing a response to it. If the release changes after the run, the run
must be repeated on a fresh held-out set, not on this one.

## What was not done

- The analyst was not run on this set.
- No provider credits were spent on this work.
- No production database was read. The generator uses the restored local release only.
