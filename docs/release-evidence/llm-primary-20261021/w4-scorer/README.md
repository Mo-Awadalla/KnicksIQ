# Scorer false negatives: rounding and sentence-final records (w4-scorer)

Status: VERIFIED for the two reported scoring defects. No live model calls; every number below
comes from offline rescoring of committed response artifacts.

- Base: `codex/llmp-integration` at `8bf9079` (`Merge branch 'codex/llmp-w4-bench' ...`).
  The brief's `8966292` was current when the worktree was requested; the w4-bench merge landed
  minutes later and changed no scoring code.
- Branch: `codex/llmp-w4-scorer`, worktree `~/.local/share/knicksiq/worktrees/w4-scorer`.
- Provider calls spent: 0. Only the local archive DB was read.

## The two defects

Both were reported by the live follow-up run (`w4-followups`, 10 of 38 failing turns) and are
false negatives in `tools/release`, not product behaviour.

1. `analyst_checks._same_number` took the tolerance from `min(left_places, right_places)`.
   Claim numbers are stored as floats with no written form, so `right_places` was 0 and the
   tolerance collapsed to exact equality: 116.3 against 116.28571428571429 failed, as did
   +2.8 against 2.8095238095238093.
2. `followup_oracle.RECORD_PAIR` ended with `(?![\w.])`. A sentence-final `69-32.` was not a
   pair, so a correct record failed the oracle even though the honest scorer passed it.

## How a fix could inflate scores, and the negative check for each

The guard script is `scoring_guard.py`; `before/scoring_guard.txt` is the pre-fix run
(19/29 checks) and `after/scoring_guard.txt` the post-fix run (29/29).

| Inflation mode | Why it is a risk | Negative check (must stay false) |
| --- | --- | --- |
| Accepting wrong rounding | A tolerance taken from the claim's full float, or a fixed epsilon, accepts 116.4 for 116.2857 | `_same_number(116.4, 116.2857, "116.4", "")`, `6.34 vs 6.3293`, `116.3 vs 116.381` (truncation) |
| Accepting a different number that rounds the same at lower precision | `_backed` also tries `value/100`; a fractional tolerance would let a plain 2.8 match a claim 0.0, and a plain 45 already matched 0.45 exactly | `_same_number(0.54, 1.0, "54", "")`, `_backed(54, [1.0])`, `_backed(2.8, [0.0])`, `_backed(45, [0.45])` |
| Integer answers riding on integer counts | The same tolerance for a written integer lets a derived 54 match 53.6 or a game id 1.0 | `_same_number(116 vs 116.2857, "116")`, `_same_number(54, 53.6, "54")` |
| Accepting a reversed record | A relaxed boundary could turn 32-69 into 69-32 | `matches_record("32-69.", 69, 32, 101)`, `"32-69, done."`, `"32 wins and 69 losses"` |
| Accepting a date as a record | The old lookbehind allowed the `01-21` tail of `2026-01-21` to match a 1-21 record | `matches_record("2026-01-21", 1, 21, 22)`, date inside a sentence |
| Accepting a decimal or domain tail | Allowing `.` must not make `69-32.5` or `69-32.txt` a record | both must stay false |

The date-as-record check exposed a **pre-existing** false acceptance: the old regex returned
`True` for `2026-01-21` as record 1-21 over 22 games. The percent check also exposed one: a
plain 45 was accepted against a 0.45 rate because every number was divided by 100. Both are
tightened here; neither had any effect on the recorded artifacts (0 changed rows).

## Root fix

`tools/release/analyst_checks.py`:

```python
written = [decimal places of each non-empty raw form]
if not written: return False          # date parts and pair values stay exact
places = min(written)
if places == 0: return False          # a written integer gets no rounding slack
return abs(left - right) <= 0.5 * 10 ** (-places) + 1e-9
```

- When both forms are written, the minimum precision is unchanged.
- When only the answer is written (the reported bug), its precision now applies.
- Integers stay exact so counts, game ids and the `/100` form cannot back a different number.
- `_backed` now offers the `/100` candidate only for a `%` token, not for every number.

`tools/release/followup_oracle.py`:

```python
RECORD_PAIR = re.compile(r"(?<![\w.-])(\d{1,3})\s*-\s*(\d{1,3})(?![\w-]|\.\w)")
```

A trailing dot at end of sentence/whitespace is allowed. A dot followed by a word character
(`.5`, `.txt`), a following hyphen, or a preceding hyphen (the ISO-date tail) is not.

`tools/release/followup_bench.py` gained `--responses`: the offline rescore path for the
follow-up artifact, mirroring `analyst_live_e2e.py --responses`; the rescore code is in
`tools/release/followup_rescore.py`. The artifact keeps only a citation projection (metric,
value, phase, game count) and drops receipt text, so the rescore rebuilds claims in the
emitted statement shape and restores the numbers the live run already proved backed from its
recorded `checks`. Only previously unbacked tokens are re-tested. The pre-fix rescore of the
recorded artifact reproduces it exactly: 90/128 turns, 24/54 sessions, causes
`{pipeline:degraded: 23, answer:value: 12, answer:declined: 2, scope: 1}`.

## Reproduction and rescore

```sh
cd ~/.local/share/knicksiq/worktrees/w4-scorer
uv sync --all-packages --all-extras --dev
. /tmp/go.env                       # DB_URL for the restored archive; no model call
uv run --package knicksiq-api python \
  docs/release-evidence/llm-primary-20261021/w4-scorer/scoring_guard.py

# before = base commit; after = this branch
D=docs/release-evidence/llm-primary-20261021/w4-scorer
uv run --package knicksiq-api python tools/release/analyst_live_e2e.py --heldout \
  --responses docs/release-evidence/llm-primary-20261021/scoring/heldout-60.responses.jsonl \
  --out $D/after/heldout-60.json
for t in 1 2; do
  uv run --package knicksiq-api python tools/release/analyst_live_e2e.py \
    --responses docs/release-evidence/llm-primary-20261021/final/budget-16000.trial$t.responses.jsonl \
    --out $D/after/budget-16000-trial$t.json
  uv run --package knicksiq-api python tools/release/analyst_live_e2e.py \
    --responses docs/release-evidence/llm-primary-20261021/w4-bench/trial$t.responses.jsonl \
    --out $D/after/w4-bench-trial$t.json
done
uv run --package knicksiq-api python tools/release/followup_bench.py \
  --responses docs/release-evidence/llm-primary-20261021/w4-followups/followup_sessions.json \
  --out $D/after/followups.json
uv run --package knicksiq-api python $D/compare.py
```

`compare.py` writes `comparison.json` and exits non-zero if any row flips pass -> fail.

## Before -> after per category

`Before` is the same offline scorer on the base commit; the tools' `old` column (validated
outcome) is not used.

### heldout-60 (60 questions)

| Category | Questions | Before | After |
| --- | ---: | ---: | ---: |
| exact_statistics | 9 | 1 | 1 |
| date_range_last_n | 9 | 1 | 1 |
| comparisons | 8 | 0 | 0 |
| single_game_narrative | 8 | 1 | 1 |
| turning_points | 8 | 0 | 0 |
| aliases_typos | 8 | 0 | 0 |
| unsupported | 10 | 1 | 1 |
| **Total** | **60** | **4** | **4** |

### budget-16000.trial1 (70 questions)

| Category | Questions | Before | After |
| --- | ---: | ---: | ---: |
| exact_statistics | 10 | 9 | 10 |
| date_range_last_n | 10 | 6 | 6 |
| comparisons | 10 | 5 | 5 |
| single_game_narrative | 10 | 3 | 3 |
| turning_points | 10 | 4 | 4 |
| aliases_typos | 10 | 4 | 4 |
| unsupported | 10 | 4 | 4 |
| **Total** | **70** | **35** | **36** |

### budget-16000.trial2 (70 questions)

| Category | Questions | Before | After |
| --- | ---: | ---: | ---: |
| exact_statistics | 10 | 8 | 10 |
| date_range_last_n | 10 | 6 | 6 |
| comparisons | 10 | 5 | 6 |
| single_game_narrative | 10 | 2 | 2 |
| turning_points | 10 | 4 | 4 |
| aliases_typos | 10 | 5 | 5 |
| unsupported | 10 | 5 | 5 |
| **Total** | **70** | **35** | **38** |

### w4-bench.trial1 (70 questions)

| Category | Questions | Before | After |
| --- | ---: | ---: | ---: |
| exact_statistics | 10 | 6 | 8 |
| date_range_last_n | 10 | 6 | 6 |
| comparisons | 10 | 3 | 3 |
| single_game_narrative | 10 | 1 | 1 |
| turning_points | 10 | 5 | 5 |
| aliases_typos | 10 | 8 | 8 |
| unsupported | 10 | 7 | 7 |
| **Total** | **70** | **36** | **38** |

### w4-bench.trial2 (70 questions)

| Category | Questions | Before | After |
| --- | ---: | ---: | ---: |
| exact_statistics | 10 | 7 | 9 |
| date_range_last_n | 10 | 8 | 8 |
| comparisons | 10 | 2 | 2 |
| single_game_narrative | 10 | 2 | 2 |
| turning_points | 10 | 4 | 4 |
| aliases_typos | 10 | 5 | 5 |
| unsupported | 10 | 7 | 7 |
| **Total** | **70** | **35** | **37** |

### w4-followups (27 sessions x 2 trials, 128 turns)

| Category | Turns | Before | After | Session runs Before | After |
| --- | ---: | ---: | ---: | ---: | ---: |
| phase_change | 32 | 27 | 28 | 9/14 | 10/14 |
| home_road | 12 | 10 | 12 | 2/4 | 4/4 |
| opponent_switch | 14 | 9 | 11 | 1/6 | 3/6 |
| player_switch | 8 | 6 | 6 | 3/4 | 3/4 |
| pronoun | 4 | 4 | 4 | 2/2 | 2/2 |
| window_change | 12 | 8 | 11 | 4/6 | 5/6 |
| aggregation | 4 | 1 | 1 | 0/2 | 0/2 |
| game_reference | 6 | 5 | 5 | 1/2 | 1/2 |
| explanation | 4 | 2 | 2 | 0/2 | 0/2 |
| decline | 18 | 10 | 10 | 0/6 | 0/6 |
| topic_retention | 10 | 7 | 7 | 2/4 | 2/4 |
| metric_change | 4 | 1 | 3 | 0/2 | 1/2 |
| **Total** | **128** | **90** | **100** | **24/54** | **31/54** |

The 100/128 reproduces the follow-up report's own prediction for both fixes; the remaining 28
failures are its fallback/reviewer, state, wording and commit classes.

## Every changed verdict (18; all false -> true, 0 pass -> fail)

| Artifact | Row | Before | After | Reason |
| --- | --- | --- | --- | --- |
| budget-16000.trial1 | exact_statistics-004 | fail | pass | 6.33 is 6.329268292682927 rounded to 2dp |
| budget-16000.trial2 | exact_statistics-003 | fail | pass | +6.33 is 6.329268292682927 rounded to 2dp |
| budget-16000.trial2 | exact_statistics-004 | fail | pass | +6.33 is 6.329268292682927 rounded to 2dp |
| budget-16000.trial2 | comparisons-010 | fail | pass | +16.25 is 16.245283018867923 rounded to 2dp |
| w4-bench.trial1 | exact_statistics-003 | fail | pass | 116.5 is 116.45121951219512 to 1dp; +6.3 is 6.329268292682927 to 1dp |
| w4-bench.trial1 | exact_statistics-004 | fail | pass | +6.33 to 2dp; 116.5 is 116.45121951219512 to 1dp |
| w4-bench.trial2 | exact_statistics-003 | fail | pass | +6.33 is 6.329268292682927 rounded to 2dp |
| w4-bench.trial2 | exact_statistics-004 | fail | pass | +6.33 is 6.329268292682927 rounded to 2dp |
| w4-followups | phase_all_then_regular t2 t1 | answer:value | ok | record 69-32 over 101 accepted sentence-final |
| w4-followups | team_ppg_home_away_playoffs t1 t2 | answer:value | ok | +2.8 is 2.8095238095238093 to 1dp |
| w4-followups | team_ppg_home_away_playoffs t2 t2 | answer:value | ok | +2.8 is 2.8095238095238093 to 1dp |
| w4-followups | team_month_switch t1 t2 | answer:value | ok | +2.93 is 2.933333333333333 to 2dp |
| w4-followups | team_month_switch t2 t1 | answer:value | ok | +5.2 is 5.214285714285714 to 1dp |
| w4-followups | team_month_switch t2 t2 | answer:value | ok | +2.9 is 2.933333333333333 to 1dp |
| w4-followups | team_margin t1 t2 | answer:value | ok | +5.2 is 5.214285714285714 to 1dp |
| w4-followups | team_margin t2 t2 | answer:value | ok | +5.2 is 5.214285714285714 to 1dp |
| w4-followups | opponent_switch_team_stats t1 t2 | answer:value | ok | 116.3 is 116.28571428571429 to 1dp; +10.3 is 10.285714285714286 to 1dp |
| w4-followups | opponent_switch_team_stats t2 t2 | answer:value | ok | 116.3 is 116.28571428571429 to 1dp; +10.3 is 10.285714285714286 to 1dp |

Session runs that became passes (24 -> 31): `phase_all_then_regular` t2,
`team_ppg_home_away_playoffs` t1 and t2, `team_month_switch` t2, `team_margin` t2,
`opponent_switch_team_stats` t1 and t2.

## Checks run

- `scoring_guard.py`: 19/29 before, 29/29 after.
- Offline rescore of all five response artifacts and the follow-up artifact, before and after.
- `compare.py`: 18 changed verdicts, all justified above; `pass->fail changes: 0`.
- `ruff check` and `ruff format --check` on the five touched scripts; `py_compile` on
  `followup_bench.py`. The full backend gate is left to the integration owner.

Artifacts: `scoring_guard.py`, `compare.py`, `tools/release/followup_rescore.py`, `before/` and
`after/` (`*.json` summaries,
`*.scored.jsonl` per-row verdicts, guard output), `comparison.json`, `comparison.txt`,
`README.md`.
