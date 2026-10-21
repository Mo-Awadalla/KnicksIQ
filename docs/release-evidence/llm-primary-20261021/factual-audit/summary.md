# Independent factual audit: final3-n70

Responses audited: 70. `meets_expectation` passes: 37. Passes that survive this audit as correct behavior: 25/37 (21 substantive answers plus 4 appropriate declines on unsupported questions). Of the substantive passes, 7 use all-phase totals where a regular-season reading gives a different number (see below).

Oracle: independent SQL over the local restored release `2025-26.20260928.1` (101 games: 82 regular season, 19 playoffs). No application calculation code was used.

Detail files: `incorrect.md`, `unsupported.md`, `missed-answers.md`. Machine-readable verdicts are in `verdicts/<category>.jsonl`.

## Verdicts

| Verdict | Count |
| --- | ---: |
| CORRECT | 25 |
| INCORRECT | 9 |
| UNSUPPORTED_CLAIM | 4 |
| DECLINE_APPROPRIATE | 6 |
| DECLINE_MISSED_ANSWER | 25 |
| INSUFFICIENT | 1 |
| **Total** | **70** |

Hand-labeled rows: 46/70. Numeric claims in those rows are still compared with SQL; the label covers only question interpretation or polite-decline judgment.

## By category

| Category | CORRECT | INCORRECT | UNSUPPORTED | DECLINE_OK | MISSED | INSUFFICIENT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| exact_statistics | 8 | 2 | 0 | 0 | 0 | 0 |
| date_range_last_n | 4 | 1 | 0 | 0 | 5 | 0 |
| comparisons | 2 | 0 | 1 | 0 | 7 | 0 |
| single_game_narrative | 3 | 0 | 0 | 1 | 5 | 1 |
| turning_points | 4 | 1 | 0 | 0 | 5 | 0 |
| aliases_typos | 2 | 4 | 1 | 0 | 3 | 0 |
| unsupported | 2 | 1 | 2 | 5 | 0 | 0 |

## Pass audit

The 37 `meets_expectation` passes break down as follows:

- Correct substantive answers: 21
- Appropriate declines on unanswerable questions: 4
- Missed answers: 5
- Factually wrong: 6
- Unsupported claim: 1

Passes that do not survive:

| id | verdict | reason |
| --- | --- | --- |
| exact_statistics-010 | INCORRECT | Team highest-scoring game is 146 points, 146-112 vs UTA on 2025-12-05 (game 22). The 47 is the player high, a different question. |
| date_range_last_n-005 | DECLINE_MISSED_ANSWER | 18-9 in 27 regular-season games after the break (2026-02-19 to 2026-04-12); 34-12 including playoffs. |
| date_range_last_n-006 | INCORRECT | 5-3 in 8 road games in December (LWWWLWWL). The 5 wins are right; the 0 losses and 5-game count are not. |
| date_range_last_n-008 | DECLINE_MISSED_ANSWER | Jalen Brunson led the Knicks over the last 3 games with 113 points (37.7 ppg). |
| date_range_last_n-009 | DECLINE_MISSED_ANSWER | 9 games between 2026-03-01 and 2026-03-15. |
| date_range_last_n-010 | DECLINE_MISSED_ANSWER | 7-3 in the first 10 games, with 1,218 points and +91 margin (all regular season). |
| comparisons-004 | DECLINE_MISSED_ANSWER | First 10: 7-3, 121.8 ppg, +91. Last 10: 9-1, 114.1 ppg, +119. The last 10 had the better record and margin; the first 10 scored more. |
| aliases_typos-003 | UNSUPPORTED_CLAIM | The release has 82 regular-season and 19 playoff games, and zero play_in games. There is no '2025-26 play-in' scope. |
| aliases_typos-004 | INCORRECT | The 2026-03-03 line is correct, but Towns has five appearances vs TOR, not one: 17.4 ppg, 13.6 rpg, 3.2 apg over five games. |
| aliases_typos-006 | INCORRECT | The Knicks went 6-3 vs ATL (2-1 regular season, 4-2 playoffs). The answer gives only one player's line from one game, so it does not answer 'how did they do'. |
| aliases_typos-009 | INCORRECT | OG averaged 11.5 over two appearances, but no player rows are missing: game 20 has 12 NYK rows and game 53 has 14. Anunoby simply did not appear in those two games. |
| unsupported-007 | INCORRECT | The decline is appropriate, but the latest dated game is 2026-06-13, not 2025-12-21. |

## Meets-expectation false negatives

The phrase-match screen marked these responses as failures, but the audit finds them correct:

| id | verdict | why |
| --- | --- | --- |
| comparisons-002 | CORRECT | Towns 19.2 over 94 appearances, Brunson 26.5 over 93. Correct, though the answer does not state the conclusion that Brunson scored more. |
| single_game_narrative-002 | CORRECT | All five Toronto dates are correct; asking which game is appropriate. |
| unsupported-005 | DECLINE_APPROPRIATE | The date 2099-01-01 is outside the archive, so declining is correct. The blanket claim that possession-level data is unavailable is false for 2025-26: event-level play-by-play exists. |
| unsupported-009 | CORRECT | There are two Lakers games, so asking which one is correct. The benchmark label says not answerable; the archive has both games. |
| unsupported-010 | CORRECT | There are four Celtics games, so asking which one is correct. The benchmark label says not answerable; the archive has all four. |

## Tone and framing flags

- `process_leak`: Mentions internal tool rounds to the user. (single_game_narrative-006)
- `tool_output_dump`: Dumps raw aggregate fields instead of answering or declining. (unsupported-006)
- `internal_jargon`: Uses internal schema terms such as game_result = W. (comparisons-010)
- `stale_scope`: Claims a play-in scope that does not exist in the release. (aliases_typos-003)
- `stale_current_framing`: Uses current/standings framing the archive cannot support. (unsupported-006)
- `stale_recency`: States a false latest-game date. (unsupported-007)
- `speculation_framing`: Offers a historical average as if it were a forecast. (unsupported-008)
- `question_drift`: Answers a different statistic than the one asked. (exact_statistics-010)
- `tool_artifact`: Leaks a filtered-set artifact such as '0 losses in that filtered set'. (exact_statistics-008)
- No betting advice or gambling recommendation appears in any response.

## Flags

- `season_scope` x7: exact_statistics-001, exact_statistics-002, exact_statistics-003, exact_statistics-004, exact_statistics-005, exact_statistics-006, exact_statistics-007
- `incomplete_matchup_list` x3: single_game_narrative-004, single_game_narrative-009, turning_points-010
- `benchmark_label_wrong` x2: unsupported-009, unsupported-010
- `tool_artifact` x1: exact_statistics-008
- `question_drift` x1: exact_statistics-010
- `internal_jargon` x1: comparisons-010
- `process_leak` x1: single_game_narrative-006
- `stale_scope` x1: aliases_typos-003
- `tool_output_dump` x1: unsupported-006
- `stale_current_framing` x1: unsupported-006
- `stale_recency` x1: unsupported-007
- `speculation_framing` x1: unsupported-008

## Season scope on the seven all-phase answers

These answers say 'archive' or 'across 101 games' and are correct under that reading. A user asking 'this season' may mean the regular season, where every value differs:

| Metric | All-phase (used) | Regular season |
| --- | ---: | ---: |
| Record | 69-32 | 53-29 |
| Points | 11,750 | 9,549 |
| Points per game | 116.3366 | 116.4512 |
| Average margin | 7.9406 | 6.3293 |
| Home wins | 37 | 30 |
| Road wins | 32 | 23 |

Affected: exact_statistics-001, exact_statistics-002, exact_statistics-003, exact_statistics-004, exact_statistics-005, exact_statistics-006, exact_statistics-007.

## Audit notes

- Integrity: 101 games, 101 distinct nba_game_ids, 0 team-score mismatches, 0 period-score mismatches. No game is double-counted.
- Rounding: every one-decimal average matched its SQL value within 0.05 and every two-decimal value within 0.005. No rounding error was found.
- `game_events` holds 46,500 play-by-play rows for all 101 games, and `period_scores` covers all 101 games. Answers that say the archive has no play-by-play, possession, quarter or halftime data are contradicted by the restore.
- `team_game_stats` has two rows per game (one per team); every query here filters `team_id = 'NYK'`. Unfiltered team-stat sums double count.
- 2025-26 player averages here exclude zero-minute DNP rows when the answer says "appearances". Towns has 96 rows, 94 appearances; that is why 19.2 and 11.6 over 94 reconcile.
- `unsupported-009` and `unsupported-010` are labelled not answerable in the benchmark, but the archive has two Lakers games and four Celtics games. The responses ask which game, which is correct; the labels are wrong.
- Reproduction: `python3 audit.py` runs every query in `queries_core.sql` and `queries_events.sql` through psql and rewrites all report files.
