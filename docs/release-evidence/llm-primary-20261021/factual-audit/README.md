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

## Result

| Set | Responses | Found | Verified | Wrong | Unverified | Checked coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 16,000 trial 1 | 70 | 523 | 515 | 8 | 0 | 100% |
| 16,000 trial 2 | 70 | 465 | 413 | 9 | 43 | 90.8% |
| correctness acceptance | 36 | 124 | 108 | 0 | 16 | 87.1% |

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
single-game output, but the archive maximum is 40. Forty-three atoms are
unverified because trial 2 phrases several player lines and score lists in
forms this audit does not bind (`single_game_narrative-003`,
`turning_points-001`, and `aliases_typos-002` are the largest groups). They are
reported as unverified, not as passes.

### Correctness acceptance

Zero wrong numbers. Sixteen atoms are unverified: fallback answers for
`exact_statistics-008/009` that name an extreme without a recognizable subject
form, and player lines whose answer omits the opponent or the per-game subject
needed to choose one SQL scope. They are not counted as passes.

## Diff against the old audit

Each output directory contains `diff.md`, a per-response table of old verdict,
new verdict, found, wrong and unverified counts. The old numeric claim count
(45 per 16,000 trial) is replaced by 523 and 465 atoms. The old audit reported
zero numeric failures in both trials while its own pass list included the two
wrong fallback responses above. Old `CORRECT` and decline verdicts that this
audit downgrades to `INCORRECT` or `UNVERIFIED` are labelled
`old pass downgraded`.

## Rerun

```sh
./run.sh
```

`run.sh` rebuilds old-audit verdicts from commit `5b585e6` in a temporary
directory, reruns all three response sets, and rewrites `trial1/`, `trial2/`
and `acceptance/`. It needs the local restore container
`kiq-integrate-postgres-1`; override with `KIQ_PSQL` if the container name
differs.

## Limitations

- The audit binds a number only when its sentence states enough subject, phase,
  window and type to choose one SQL scope. Trial 2 and the acceptance fallback
  rows show where that fails; those atoms stay unverified.
- `comparisons-002` is flagged wrong on a semantic maximum claim (39 against the
  actual maximum 40). The value 39 exists as a Towns game, but the sentence
  calls it the maximum.
- Score pairs match either orientation when the sentence names no scoring
  subject; the detail field records that orientation was not asserted.
- Dates and clock labels are verified as identities and endpoints, not as
  evidence that a narrative is causally correct.
