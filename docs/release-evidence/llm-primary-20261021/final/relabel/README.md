# Held-out relabel under the season-phase policy

Branch `relabel` from `codex/llm-integration` at `5ddfddc`. No live provider call was made in
this task. The held-out responses from `final/heldout-60.responses.jsonl` and the committed
baseline `scoring/heldout-60.responses.jsonl` were re-scored offline with the same labels.

The season-phase policy was decided by the lead on 2026-10-21, before the held-out run:
season-level records and stats default to the regular season unless the question names
playoffs or `overall`/`including playoffs`/`all phases`; opponent and player-vs-opponent
questions cover all phases. The held-out labels were generated before that decision and
several of them used all-phase populations. This relabel regenerates them under the policy.

## Why this is not label-fitting, and the fences

Relabeling a held-out set after seeing the answers can manufacture a pass rate. The
following abuses were identified before the labels changed, and each is fenced:

| Abuse | Fence applied here |
| --- | --- |
| Choose the value that the observed answer happens to contain | The generator never reads a response. Phase comes from the question text through the ordered policy table in `heldout_phase.py`; values come from SQL over the active release. No response path is an input to `build_heldout_set.py`. |
| Use the responses to decide which phase a question means | `phase_policy(question)` sees only the question string. The per-row phase and the matching rule are in `phase-policy.json`; every question resolves. The held-out run files were opened only after the new labels existed. |
| Edit a question or id so a row becomes easier | A SHA-256 digest of the ordered `(category, question)` list is a constant in the generator. Changing a question or its order stops generation. `questions-stable.json` records the same pairs hash before and after and an empty pairs diff. |
| Drop hard questions, categories or rows | The generator still requires exactly 60 cases and the same seven category counts. The audit script asserts all 60 ids exist in both label files and both rescored files. |
| Loosen the scorer so both readings pass | The scorer keeps the same fact rule and tolerance. It has one proven bug fix: `fact_ok` discarded the written number forms, so the existing `_same_number` precision tolerance was unreachable and a label of 7.57 could never match a correct answer of 7.6. The fix passes the written forms; it adds no OR rule and no new tolerance. See `scorer-precision-proof.py`. |
| Accept both phases whenever a row fails | Dual acceptance is not used. Every answerable row resolves to one phase or to `both` where the question names both phases. The list is in `phase-policy.json`. |
| Report only the better run | Both the new live run and the committed baseline are rescored with the identical new label file and command. Both tables are below, including the row the baseline loses. |
| Hide verdict changes | `verdict-changes.json` lists every changed `meets_expectation` for both runs with the old and new failure lists and the reason. |
| Change the baseline responses | The two response files are hashed before the rescore and are not edited. |

The generator change is limited to the phase population and to one pre-existing metric bug:
`player_avg` divided by every player-game row, including rows with `minutes = 0` (a
did-not-play row is not an appearance). The same `minutes > 0` appearance rule is applied to
every player average in every phase. It is not selected per row from the answers; the
before/after values and the SQL are in `label-diff.json`, and rows changed only by this rule
are labelled `appearance_population` rather than `phase`.

## Policy table

`apps/api/app/evaluation/heldout_phase.py` resolves the phase from the question text with
these ordered rules. The first match wins.

| Order | Rule (question text) | Phase | Population |
| ---: | --- | --- | --- |
| 1 | a specific game: `Game N` or a month plus day or an ISO date | `game` | the named game |
| 2 | `overall`, `including playoffs` or `all phases` | `all` | every phase |
| 3 | both `regular season` and `playoffs`/`postseason` in one question | `both` | both phases, reported separately |
| 4 | `playoffs` or `postseason` | `playoffs` | playoffs only |
| 5 | `play in` as a tournament phrase, not the verb `play in <month>` | `play_in` | play-in only |
| 6 | `regular season` | `regular` | regular season only |
| 7 | a named opponent (team nickname, city or code) | `all` | every phase |
| 8 | a named month or an ISO date window with no day | `window` | every phase inside the window; the window itself decides |
| 9 | a relative window: `last/first/final/previous N games` or `... appearances` | `all` | every phase (a relative window is not season-level) |
| 10 | otherwise | `regular` | season-level default |

Two questions name two phases (`comparisons-004`, `comparisons-006`); their facts are emitted
for the regular season and the playoffs separately, so no ambiguity exists.

Genuinely ambiguous rows under this table: none. `full season` in
`heldout-exact_statistics-002` is not one of the policy's all-phase phrases and the policy
default is explicit, so only the regular-season value is accepted. `first 15 games` and
`last 6 appearances` are relative windows; both populations lie inside the same phase set, so
the rule does not admit a second value. No dual acceptance is used.

`date_range_last_n-007` (`How many games did the Knicks play in November?`) exposed a live
app bug: `query_resolution.py` tests the substring `play in`, so the question is resolved as
a play-in question and returns no games. The held-out policy table uses the tournament
reading of `play in`, so the label is the correct November window (14 games). The row stays
failed for the app bug; it is not relabelled to 0.

## Scorer precision bug

`tools/release/analyst_scoring.py` changed in one place. `fact_ok` built its wanted values
with `_numbers_in`, which returns floats and drops the written text, then called
`_same_number(value, item)` without raw strings. `_same_number` only applies its half-unit
tolerance when the raw text is present, so the tolerance was unreachable for required facts.
A correct one-decimal answer (7.6) could never match a two-decimal label (7.57) even though
both round to the same value. `_fact_numbers` now keeps each number's written form and the
comparison passes both forms; the same tolerance rule is used, nothing is widened.

Proof and the unchanged old behaviour:

```sh
$ uv run --package knicsiq-api python \
    docs/release-evidence/llm-primary-20261021/final/relabel/scorer-precision-proof.py
floats only:         False
written forms:       True
required_facts_ok:   True
```

The committed final held-out row for `heldout-date_range_last_n-006` is the same shape:
label 5.63, answer 5.6, `required_facts_ok` false before the fix. All four tables below use
the fixed scorer so the comparison is like for like. Under the old labels the fix moves the
final run from 20 to 21 and leaves the baseline at 5; the new labels score 29 and 4.

## Results

Both response files, old labels and new labels, same command and same scorer. `meets_expectation`
is the honest check. The `old screen` column in the harness output is not a quality number and
is omitted here.

### Live held-out run (`final/heldout-60.responses.jsonl`)

| Category | Questions | Old labels | New labels |
| --- | ---: | ---: | ---: |
| aliases_typos | 8 | 5 | 6 |
| comparisons | 8 | 0 | 3 |
| date_range_last_n | 9 | 3 | 3 |
| exact_statistics | 9 | 1 | 5 |
| single_game_narrative | 8 | 0 | 0 |
| turning_points | 8 | 3 | 3 |
| unsupported | 10 | 9 | 9 |
| Total | 60 | 21 | 29 |

Old labels, claim-backed: 21. New labels, claim-backed: 29. The committed run's honest
number was 20 with the pre-fix scorer; the fixed scorer accepts the already-correct
`heldout-date_range_last_n-006` (5.63 label, 5.6 answer).

### Committed baseline (`scoring/heldout-60.responses.jsonl`)

| Category | Questions | Old labels | New labels |
| --- | ---: | ---: | ---: |
| aliases_typos | 8 | 0 | 0 |
| comparisons | 8 | 0 | 0 |
| date_range_last_n | 9 | 1 | 1 |
| exact_statistics | 9 | 2 | 1 |
| single_game_narrative | 8 | 1 | 1 |
| turning_points | 8 | 0 | 0 |
| unsupported | 10 | 1 | 1 |
| Total | 60 | 5 | 4 |

The baseline gets worse under the correct labels, as it should: its answers were written to
the old all-phase expectations. The lost row is `heldout-exact_statistics-004`, where the
baseline says 12 home losses (all-phase) and the policy population is 10.

### Rows that changed verdict

Live run, 8 gained, none lost:

| Row | Old failure | Why it now passes |
| --- | --- | --- |
| exact_statistics-002 | required_facts | 116.34 all-phase becomes 116.45 regular; answer states 116.45 over 82 |
| exact_statistics-004 | required_facts | 12 all-phase home losses becomes 10 regular; answer states 10 |
| exact_statistics-006 | required_facts | 2.1 all-phase/all-rows becomes 2.6 regular appearances; answer states 2.6 |
| exact_statistics-008 | required_facts | 7.0 all-phase/all-rows becomes 8.6 regular appearances; answer states 8.6 |
| comparisons-001 | required_facts | 9.80/8.41 all-phase/all-rows becomes 11.98/9.31 regular appearances; answer states 12.0/9.3 |
| comparisons-002 | required_facts | 7.90/1.93 becomes 8.75/2.94 regular appearances; answer states 8.8/2.9 |
| comparisons-005 | required_facts | 2.11/1.23 becomes 2.59/1.41 regular appearances; answer states 2.6/1.4 |
| aliases_typos-003 | required_facts | phase is unchanged (opponent); the old label divided by a zero-minute DNP and becomes 7.57 observed; answer states 7.6 |

Baseline, 1 lost, none gained:

| Row | Old failure | Why it now fails |
| --- | --- | --- |
| exact_statistics-004 | none | The baseline says 12 home losses, correct only under the old all-phase label; the policy population is 10 regular-season home losses |

`verdict-changes.json` carries the old and new failure lists and the answers for all nine.

### Rows still failing `required_facts` (26 of 60, live run)

None of the remaining 26 is a phase-label disagreement:

- 13 are archive-coverage or query-scope gaps: the answer says a split, aggregate or
  opponent breakdown is not in the returned evidence (`exact_statistics-005/007/009`,
  `date_range_last_n-001/002/005/007/008`, `comparisons-003/004/006/007/008`). The November
  row is the app's `play in` substring bug above.
- 8 single-game narratives give the final score but omit the top scorer's point total
  (`single_game_narrative-001/003/005/006/007/008`) or return a clarification
  (`-002`/`-004`).
- 4 turning-point answers name a quarter or a run that is not the largest-margin quarter the
  label asks for (`turning_points-002/004/006/008`).
- 1 alias answer is a clarification listing the PHI game ids (`aliases_typos-005`).

## Commands

```sh
# new labels from the local release
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicsiq-api python -m app.evaluation.build_heldout_set

# old labels, unchanged, from the base commit
git show 5ddfddc:apps/api/app/evaluation/heldout_questions.jsonl > /tmp/heldout-labels-before.jsonl

# four offline rescores (the only runs in this task)
D=docs/release-evidence/llm-primary-20261021/final/relabel
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicsiq-api python tools/release/analyst_live_e2e.py \
  --responses docs/release-evidence/llm-primary-20261021/final/heldout-60.responses.jsonl \
  --questions /tmp/heldout-labels-before.jsonl --out "$D/final-run.old-labels.rescored.json"
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicsiq-api python tools/release/analyst_live_e2e.py \
  --responses docs/release-evidence/llm-primary-20261021/final/heldout-60.responses.jsonl \
  --questions apps/api/app/evaluation/heldout_questions.jsonl \
  --out "$D/final-run.new-labels.rescored.json"
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicsiq-api python tools/release/analyst_live_e2e.py \
  --responses docs/release-evidence/llm-primary-20261021/scoring/heldout-60.responses.jsonl \
  --questions /tmp/heldout-labels-before.jsonl --out "$D/baseline.old-labels.rescored.json"
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicsiq-api python tools/release/analyst_live_e2e.py \
  --responses docs/release-evidence/llm-primary-20261021/scoring/heldout-60.responses.jsonl \
  --questions apps/api/app/evaluation/heldout_questions.jsonl \
  --out "$D/baseline.new-labels.rescored.json"

# proof artifacts: fact SQL, phase table, stability, verdict changes
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicsiq-api python "$D/make_label_diff.py"
```

## Artifacts

- `questions-stable.json`: hashes before and after, empty id/question diff, unchanged fields.
- `phase-policy.json`: every row's category, phase, matching rule, filters and question.
- `label-diff.json`: all 20 changed facts on 14 rows, each with the old and new SQL, the SQL
  result, the phase and the reason.
- `verdict-changes.json`: the nine changed verdicts across both runs.
- `final-run.old-labels.rescored.json` / `.scored.jsonl`
- `final-run.new-labels.rescored.json` / `.scored.jsonl`
- `baseline.old-labels.rescored.json` / `.scored.jsonl`
- `baseline.new-labels.rescored.json` / `.scored.jsonl`
- `make_label_diff.py`, `scorer-precision-proof.py`: repeatable checks.

Input hashes (before the rescore):

```
40a6f78a1d66a1be92f8081d2d084a0929155bdb21db054be0c7f5f87c32692d  old labels
7717914cbb7d786ad87f8d084a4a9b12a7abe1bbf72df55789a16e69bbc29a85  new labels
2b63663b8ce731d591f8c43cafd7fed289103df49614ab11fc38765f185777f3  final run responses
51a93e1c90bb881a07f81ac681d5cf67e29c93b974612bc06bfcb9f95132085a  baseline responses
```
