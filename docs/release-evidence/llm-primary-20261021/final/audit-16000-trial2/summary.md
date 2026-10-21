# Independent factual audit: final3-n70

Responses audited: 70. `meets_expectation` passes: 0. Passes that survive this audit as correct behavior: 0/0 (0 substantive answers plus 0 appropriate declines on unsupported questions). Of the substantive passes, 0 use all-phase totals where a regular-season reading gives a different number (see below).

Oracle: independent SQL over the local restored release `2025-26.20260928.1` (101 games: 82 regular season, 19 playoffs). No application calculation code was used.

Detail files: `incorrect.md`, `unsupported.md`, `missed-answers.md`. Machine-readable verdicts are in `verdicts/<category>.jsonl`.

## Verdicts

| Verdict | Count |
| --- | ---: |
| CORRECT | 31 |
| INCORRECT | 1 |
| UNSUPPORTED_CLAIM | 3 |
| DECLINE_APPROPRIATE | 8 |
| DECLINE_MISSED_ANSWER | 26 |
| INSUFFICIENT | 1 |
| **Total** | **70** |

Hand-labeled rows: 44/70. Numeric claims in those rows are still compared with SQL; the label covers only question interpretation or polite-decline judgment.

## By category

| Category | CORRECT | INCORRECT | UNSUPPORTED | DECLINE_OK | MISSED | INSUFFICIENT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| exact_statistics | 10 | 0 | 0 | 0 | 0 | 0 |
| date_range_last_n | 5 | 0 | 0 | 0 | 5 | 0 |
| comparisons | 2 | 0 | 1 | 0 | 7 | 0 |
| single_game_narrative | 3 | 0 | 0 | 1 | 5 | 1 |
| turning_points | 4 | 0 | 0 | 0 | 6 | 0 |
| aliases_typos | 5 | 1 | 1 | 0 | 3 | 0 |
| unsupported | 2 | 0 | 1 | 7 | 0 | 0 |

## Pass audit

The 37 `meets_expectation` passes break down as follows:

- Correct substantive answers: 0
- Appropriate declines on unanswerable questions: 0
- Missed answers: 0
- Factually wrong: 0
- Unsupported claim: 0

## Meets-expectation false negatives

The phrase-match screen marked these responses as failures, but the audit finds them correct:

| id | verdict | why |
| --- | --- | --- |
| exact_statistics-001 | CORRECT |  |
| exact_statistics-002 | CORRECT |  |
| exact_statistics-003 | CORRECT |  |
| exact_statistics-004 | CORRECT |  |
| exact_statistics-005 | CORRECT |  |
| exact_statistics-006 | CORRECT |  |
| exact_statistics-007 | CORRECT |  |
| exact_statistics-008 | CORRECT |  |
| exact_statistics-009 | CORRECT |  |
| exact_statistics-010 | CORRECT |  |
| date_range_last_n-001 | CORRECT | 4-1, 522 points, +12 over 2026-06-03 to 2026-06-13. |
| date_range_last_n-002 | CORRECT | 114.1 ppg and 9-1 over the last 10 (2026-05-10 to 2026-06-13). |
| date_range_last_n-003 | CORRECT | 32.6 over his last five appearances, 2026-06-03 to 2026-06-13. |
| date_range_last_n-004 | CORRECT | 7-8 in 15 games, 1,652 points, 2026-01-02 to 2026-01-30. |
| date_range_last_n-006 | CORRECT |  |
| comparisons-002 | CORRECT | Towns 19.2 over 94 appearances, Brunson 26.5 over 93. Correct, though the answer does not state the conclusion that Brunson scored more. |
| comparisons-008 | CORRECT | Towns 11.6 over 94 appearances, Hart 7.7 over 85. Towns had more rebounds per appearance. |
| single_game_narrative-002 | CORRECT | All five Toronto dates are correct; asking which game is appropriate. |
| single_game_narrative-007 | CORRECT | All four Boston dates are correct; asking which game is appropriate. |
| single_game_narrative-009 | CORRECT | All eight listed Atlanta dates are real; the ninth is 2026-04-30. 'Including' makes the list nonexhaustive, so this is a valid clarification. |
| turning_points-002 | CORRECT | All five Toronto dates are correct; asking which game is appropriate. |
| turning_points-004 | CORRECT | All four Chicago dates are correct; asking which game is appropriate. |
| turning_points-006 | CORRECT | All four Boston dates are correct; asking which game and defining 'drought' is appropriate. |
| turning_points-010 | CORRECT | Eight of nine Atlanta dates are listed; 2026-04-30 is missing. 'Any of these' is not exhaustive, so this remains a usable clarification. |
| aliases_typos-001 | CORRECT | 3-1 in four regular-season games vs BOS, 445 points. Correct. |
| aliases_typos-002 | CORRECT | All box-score values and the 123-117 Boston score are correct. |
| aliases_typos-004 | CORRECT |  |
| aliases_typos-006 | CORRECT |  |
| aliases_typos-009 | CORRECT |  |
| unsupported-001 | DECLINE_APPROPRIATE | No live data exists; the decline is correct. |
| unsupported-002 | DECLINE_APPROPRIATE | No predictive data exists. The 47-point Brunson line quoted is correct, though unrelated. |
| unsupported-003 | DECLINE_APPROPRIATE | No injury data exists; the decline is correct. |
| unsupported-004 | DECLINE_APPROPRIATE | No trade or recommendation data exists; the decline is correct. |
| unsupported-005 | DECLINE_APPROPRIATE | The date 2099-01-01 is outside the archive, so declining is correct. The blanket claim that possession-level data is unavailable is false for 2025-26: event-level play-by-play exists. |
| unsupported-006 | DECLINE_APPROPRIATE |  |
| unsupported-007 | DECLINE_APPROPRIATE |  |
| unsupported-009 | CORRECT | There are two Lakers games, so asking which one is correct. The benchmark label says not answerable; the archive has both games. |
| unsupported-010 | CORRECT | There are four Celtics games, so asking which one is correct. The benchmark label says not answerable; the archive has all four. |

## Tone and framing flags

- `process_leak`: Mentions internal tool rounds to the user. (single_game_narrative-006)
- `internal_jargon`: Uses internal schema terms such as game_result = W. (comparisons-010)
- `stale_scope`: Claims a play-in scope that does not exist in the release. (aliases_typos-003)
- `speculation_framing`: Offers a historical average as if it were a forecast. (unsupported-008)
- No betting advice or gambling recommendation appears in any response.

## Flags

- `incomplete_matchup_list` x3: single_game_narrative-004, single_game_narrative-009, turning_points-010
- `benchmark_label_wrong` x2: unsupported-009, unsupported-010
- `internal_jargon` x1: comparisons-010
- `process_leak` x1: single_game_narrative-006
- `stale_scope` x1: aliases_typos-003
- `speculation_framing` x1: unsupported-008

## Audit notes

- Integrity: 101 games, 101 distinct nba_game_ids, 0 team-score mismatches, 0 period-score mismatches. No game is double-counted.
- Rounding: every one-decimal average matched its SQL value within 0.05 and every two-decimal value within 0.005. No rounding error was found.
- `game_events` holds 46,500 play-by-play rows for all 101 games, and `period_scores` covers all 101 games. Answers that say the archive has no play-by-play, possession, quarter or halftime data are contradicted by the restore.
- `team_game_stats` has two rows per game (one per team); every query here filters `team_id = 'NYK'`. Unfiltered team-stat sums double count.
- 2025-26 player averages here exclude zero-minute DNP rows when the answer says "appearances". Towns has 96 rows, 94 appearances; that is why 19.2 and 11.6 over 94 reconcile.
- `unsupported-009` and `unsupported-010` are labelled not answerable in the benchmark, but the archive has two Lakers games and four Celtics games. The responses ask which game, which is correct; the labels are wrong.
- Reproduction: `python3 audit.py` runs every query in `queries_core.sql` and `queries_events.sql` through psql and rewrites all report files.
