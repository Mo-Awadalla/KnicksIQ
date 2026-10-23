# Replacement factual audit

This replaces the claim-list audit at commit `5b585e6` for the 2026-10-21
`llm_primary` responses. The old audit checked only the claims a spec listed.
Claims without an `extract` callable compared a constant copied from an older
answer, so "0 numeric failures" did not mean the delivered numbers had been
recomputed. Failure modes are written first in `failure-modes.md`.

## Method

`audit.py` extracts every numeric atom from each answer: dates, date ranges,
seasons, game numbers, clock and period labels, record pairs, score pairs, runs,
signed and unsigned integers, decimals and percentages. For each atom the
surrounding sentence supplies the subject (team or player), phase (regular
season, playoffs, all archive), window (last or first N, month, date range),
location, opponent and numeric type. The expected value is recomputed from the
raw restore tables by SQL owned by this audit:

- `oracle_db.py` loads `games`, `period_scores`, `player_game_stats`, `players`
  and `game_events` through `psql`, then rebuilds team aggregates, player lines
  and play-by-play timelines.
- `flow.py` recomputes runs, deficits erased, lost leads, go-ahead plays and
  scoreboard snapshots from consecutive scoring events.
- `verify_basic.py`, `verify_player.py`, `verify_period.py` and `verify_flow.py`
  bind atom types to those facts.
- An atom no verifier can bind is `unverified`. It is never a pass.

Each response row records found, verified, wrong, unverified, checked coverage,
and one detail record per atom with its claimed value, expected value, fact and
SQL. Wrong values are listed with SQL in `summary.md`; the machine-readable
ledger is `rows.jsonl`.

Binding rules added for the wave-4 answers (all exercised by
`flag-verdicts.md`):

- Sentences are split on sentence-ending punctuation only, so `26.0` and
  `113.67` no longer cut the phase label off the sentence.
- An atom's scope comes from its clause prefix; a phase named later in the same
  sentence fills a prefix that names none; two phase clauses ("regular season
  2-1; playoffs 4-2") take the later clause; "regular season and playoffs" means
  both phases.
- A bare `home,`/`road,` label is a location; the nearest team mention to the
  atom wins over an earlier one.
- "After the All-Star break" is a window derived from the longest gap in the
  regular-season calendar (2026-02-19 here).
- `plus-9.1` and `minus-2.9` keep the sign of the word, not the hyphen.
- A run's team comes from its start/end score snapshots, not the nearest prose.
- A date range that restates the requested window is a scope descriptor, not a
  claim that games were played on both endpoints.

## Result

| Set | Responses | Found | Verified | Wrong | Unverified | Checked coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 16,000 trial 1 | 70 | 523 | 515 | 8 | 0 | 100% |
| 16,000 trial 2 | 70 | 465 | 424 | 9 | 32 | 93.1% |
| correctness acceptance | 36 | 124 | 124 | 0 | 0 | 100% |
| w4-bench trial 1 | 70 | 597 | 384 | 0 | 213 | 64.3% |
| w4-bench trial 2 | 70 | 644 | 477 | 0 | 167 | 74.1% |

Checked coverage counts verified plus wrong over found. Unverified atoms are
listed per response in each `summary.md`.

### Trial 1

All 523 numeric atoms were checked. Eight are wrong, all in the two fallback
responses below; every other answered response has zero wrong and zero
unverified numbers.

- `date_range_last_n-009` says 10 wins and 6 losses over 16 games for March
  1-15. The archive has 6 wins and 3 losses over 9 games in that window.
- `date_range_last_n-010` says 53 wins and 29 losses over 82 games for the first
  10 games. The first 10 games are 7-3.

These are genuine wrong answers, not audit artifacts. They were
`DECLINE_MISSED_ANSWER` in the old audit, which checked only the listed period
claims and never the 10-6 or 53-29 record it reproduced.

### Trial 2

Nine wrong atoms. The eight date-range wrongs are the same two fallback
responses as trial 1. The ninth is `comparisons-002`: it calls 39 Towns' maximum
single-game output, but the archive maximum is 40. Thirty-two atoms are
unverified because trial 2 phrases several player lines and score lists in
forms this audit does not bind (`single_game_narrative-003` is the largest
group). They are reported as unverified, not as passes. Eleven atoms that were
unverified before now bind: `exact_statistics-005` (10 home losses),
`exact_statistics-007` (29 losses), `date_range_last_n-004` (15 games),
`comparisons-001` (30-10 and 23-19), and three Q4 score/clock pairs in
`single_game_narrative-003`.

### Correctness acceptance

Zero wrong numbers and zero unverified atoms. The sixteen atoms that were
unverified now bind: the `exact_statistics-008/009` extremes (54 and 120-66;
38 and 80-118), the 9-game Atlanta total, both phase records for
`aliases_typos-006`, Brunson's 47-point game, and Towns' 17.4 points per
appearance against Toronto.

## Diff against the old audit

Each output directory contains `diff.md`, a per-response table of old verdict,
new verdict, found, wrong and unverified counts. The old numeric claim count
(45 per 16,000 trial) is replaced by 523 and 465 atoms. The old audit reported
zero numeric failures in both trials while its own pass list included the two
wrong fallback responses above. Old `CORRECT` and decline verdicts that this
audit downgrades to `INCORRECT` or `UNVERIFIED` are labelled
`old pass downgraded`.

## w4-bench trials

The 2026-10-21 live benchmark's 140 answers produced 597 and 644 atoms. The
first audit run marked 21 and 15 wrong and bound only 57% and 69%. Every one of
those 36 atoms recomputes from the raw tables under the scope its sentence
states; `flag-verdicts.md` records the per-flag verdict, SQL and mis-binding,
and proves the three disputed start clocks from `game_events`. Both trials now
have zero wrong numbers; 213 and 167 atoms are still unverified (fallback
period dumps and per-game lists this audit does not bind) and are not counted as
passes.

## Rerun

```sh
./run.sh
```

`run.sh` rebuilds old-audit verdicts from commit `5b585e6` in a temporary
directory, reruns all five response sets, and rewrites `trial1/`, `trial2/`,
`acceptance/`, `w4-trial1/` and `w4-trial2/`. It needs the local restore
container `kiq-integrate-postgres-1`; override with `KIQ_PSQL` if the container
name differs.

## Limitations

- The audit binds a number only when its sentence states enough subject, phase,
  window and type to choose one SQL scope. The w4-bench fallback period dumps
  (`single_game_narrative-003/005`, `aliases_typos-007`) show where that fails;
  those atoms stay unverified.
- `comparisons-002` is flagged wrong on a semantic maximum claim (39 against the
  actual maximum 40). The value 39 exists as a Towns game, but the sentence
  calls it the maximum.
- Score pairs match either orientation when the sentence names no scoring
  subject; the detail field records that orientation was not asserted.
- Dates and clock labels are verified as identities and endpoints, not as
  evidence that a narrative is causally correct.
