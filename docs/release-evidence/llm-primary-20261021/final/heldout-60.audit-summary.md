# Independent factual audit: final3-n70

Responses audited: 60. `meets_expectation` passes: 0. Passes that survive this audit as correct behavior: 0/0 (0 substantive answers plus 0 appropriate declines on unsupported questions). Of the substantive passes, 0 use all-phase totals where a regular-season reading gives a different number (see below).

Oracle: independent SQL over the local restored release `2025-26.20260928.1` (101 games: 82 regular season, 19 playoffs). No application calculation code was used.

Detail files: `incorrect.md`, `unsupported.md`, `missed-answers.md`. Machine-readable verdicts are in `verdicts/<category>.jsonl`.

## Verdicts

| Verdict | Count |
| --- | ---: |
| CORRECT | 0 |
| INCORRECT | 0 |
| UNSUPPORTED_CLAIM | 0 |
| DECLINE_APPROPRIATE | 0 |
| DECLINE_MISSED_ANSWER | 0 |
| INSUFFICIENT | 60 |
| **Total** | **60** |

Hand-labeled rows: 60/60. Numeric claims in those rows are still compared with SQL; the label covers only question interpretation or polite-decline judgment.

## By category

| Category | CORRECT | INCORRECT | UNSUPPORTED | DECLINE_OK | MISSED | INSUFFICIENT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| exact_statistics | 0 | 0 | 0 | 0 | 0 | 9 |
| date_range_last_n | 0 | 0 | 0 | 0 | 0 | 9 |
| comparisons | 0 | 0 | 0 | 0 | 0 | 8 |
| single_game_narrative | 0 | 0 | 0 | 0 | 0 | 8 |
| turning_points | 0 | 0 | 0 | 0 | 0 | 8 |
| aliases_typos | 0 | 0 | 0 | 0 | 0 | 8 |
| unsupported | 0 | 0 | 0 | 0 | 0 | 10 |

## Pass audit

The 37 `meets_expectation` passes break down as follows:

- Correct substantive answers: 0
- Appropriate declines on unanswerable questions: 0
- Missed answers: 0
- Factually wrong: 0
- Unsupported claim: 0

## Tone and framing flags

- No betting advice or gambling recommendation appears in any response.

## Flags


## Audit notes

- Integrity: 101 games, 101 distinct nba_game_ids, 0 team-score mismatches, 0 period-score mismatches. No game is double-counted.
- Rounding: every one-decimal average matched its SQL value within 0.05 and every two-decimal value within 0.005. No rounding error was found.
- `game_events` holds 46,500 play-by-play rows for all 101 games, and `period_scores` covers all 101 games. Answers that say the archive has no play-by-play, possession, quarter or halftime data are contradicted by the restore.
- `team_game_stats` has two rows per game (one per team); every query here filters `team_id = 'NYK'`. Unfiltered team-stat sums double count.
- 2025-26 player averages here exclude zero-minute DNP rows when the answer says "appearances". Towns has 96 rows, 94 appearances; that is why 19.2 and 11.6 over 94 reconcile.
- `unsupported-009` and `unsupported-010` are labelled not answerable in the benchmark, but the archive has two Lakers games and four Celtics games. The responses ask which game, which is correct; the labels are wrong.
- Reproduction: `python3 audit.py` runs every query in `queries_core.sql` and `queries_events.sql` through psql and rewrites all report files.
