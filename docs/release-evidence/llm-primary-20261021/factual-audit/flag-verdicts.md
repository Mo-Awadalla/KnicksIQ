# Per-flag verdicts: the 36 wrong numbers on the w4-bench trials

Every number below is an atom the full SQL audit marked `wrong` in `w4-bench/audit/trialN/rows.jsonl`
before the binding fixes. For each one the delivered value was recomputed from the raw restore tables
under the scope its own sentence states. `BINDING` means the delivered number is correct and the audit
had bound the atom to the wrong scope, window, sign or game. `REAL` means the delivered number is wrong.

**Result: 36 BINDING, 0 REAL.** The three cases BenchGo called "correct run sizes with a wrong start
clock" are disproved by the play-by-play SQL below: both the run size and the start clock are correct,
and the audit had the scoring team or the game wrong.

## Trial 1 (21 atoms)

| id | atom | delivered | recomputed | SQL | verdict | mis-binding |
| --- | --- | ---: | --- | --- | --- | --- |
| exact_statistics-008 | `59` | 59 | 59 | `select max(case when g.home_team_id='NYK' then e.home_score-e.away_score else e.away_score-e.home_score end) from game_events e join games g on g.id=e.game_id where g.game_date='2026-01-21'` | BINDING | `largest lead` was bound as a lost lead |
| date_range_last_n-004 | `Jan 1–31` | '2026-01-01..2026-01-31' | '2026-01-01..2026-01-31' | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-01-01') and (game_date <= '2026-01-31') order by game_date` | BINDING | range restates the requested window; it was compared to the first/last game date |
| date_range_last_n-005 | `27` | 27 | 27 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-02-19') order by game_date` | BINDING | post-All-Star-break window not modeled |
| date_range_last_n-005 | `113.26` | 113.26 | 113.25925925925925 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-02-19') order by game_date` | BINDING | post-All-Star-break window not modeled |
| date_range_last_n-005 | `106.59` | 106.59 | 106.5925925925926 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-02-19') order by game_date` | BINDING | post-All-Star-break window not modeled |
| date_range_last_n-005 | `+6.67` | 6.67 | 6.666666666666667 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-02-19') order by game_date` | BINDING | post-All-Star-break window not modeled |
| comparisons-001 | `40` | 40 | 40 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (home_team_id='NYK') order by game_date` | BINDING | home clause inherited the question's "on the road" location |
| comparisons-001 | `119.00` | 119.0 | 119.0 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (home_team_id='NYK') order by game_date` | BINDING | home clause inherited the question's "on the road" location |
| comparisons-001 | `108.97` | 108.97 | 108.975 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (home_team_id='NYK') order by game_date` | BINDING | home clause inherited the question's "on the road" location |
| comparisons-001 | `+10.03` | 10.03 | 10.025 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (home_team_id='NYK') order by game_date` | BINDING | home clause inherited the question's "on the road" location |
| comparisons-004 | `9.1` | 9.1 | 9.1 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date asc limit 10` | BINDING | `plus-9.1` was tokenized as negative 9.1 |
| comparisons-004 | `2.9` | 2.9 | 2.9 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date desc limit 10` | BINDING | `plus-2.9` was tokenized as negative 2.9 |
| single_game_narrative-003 | `9` | 9.0 | 9 | `games where ('NYK' in (home_team_id, away_team_id)) and (((home_team_id='NYK' and away_team_id='ATL') or (away_team_id='NYK' and home_team_id='ATL'))) order by game_date` | BINDING | `Regular season and playoffs` was bound to playoffs only |
| single_game_narrative-003 | `9` | 9 | 9 | `games where ('NYK' in (home_team_id, away_team_id)) and (((home_team_id='NYK' and away_team_id='ATL') or (away_team_id='NYK' and home_team_id='ATL'))) order by game_date` | BINDING | `Regular season and playoffs` was bound to playoffs only |
| turning_points-005 | `8-0` | '8-0' | '8-0 Q2 00:08 to Q3 10:47' | `select sequence, period, clock, team_id, home_score, away_score from game_events where game_id=69 and sequence between 214 and 230 order by sequence` | BINDING | run attributed to GSW by nearby text; the snapshots identify a NYK run |
| turning_points-008 | `83-104` | '83-104' | '83-104 at Q4 08:32' | `select sequence, period, clock, team_id, home_score, away_score from game_events where game_id=74 and period=4 and clock='08:32'` | BINDING | sentence inherited the other game's date from the previous sentence |
| turning_points-009 | `7-0` | '7-0' | '7-0 Q3 07:46 to Q3 06:36' | `select sequence, period, clock, team_id, home_score, away_score from game_events where game_id=47 and sequence between 287 and 299 order by sequence` | BINDING | run attributed to TOR by nearby text; the snapshots identify a NYK run |
| aliases_typos-003 | `26.0` | 26.0 | 26.04054054054054 | `player_game_stats where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 and g.season_type='regular' order by g.game_date` | BINDING | phase follows the number and was not applied |
| aliases_typos-003 | `74` | 74.0 | 74 | `player_game_stats where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 and g.season_type='regular' order by g.game_date` | BINDING | phase follows the number and was not applied |
| unsupported-008 | `26.0` | 26.0 | 26.04054054054054 | `player_game_stats where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 and g.season_type='regular' order by g.game_date` | BINDING | phase follows the number and was not applied |
| unsupported-008 | `74` | 74.0 | 74 | `player_game_stats where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 and g.season_type='regular' order by g.game_date` | BINDING | phase follows the number and was not applied |

## Trial 2 (15 atoms)

| id | atom | delivered | recomputed | SQL | verdict | mis-binding |
| --- | --- | ---: | --- | --- | --- | --- |
| exact_statistics-002 | `9,549` | 9549.0 | 9549 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date` | BINDING | phase follows the number; the audit used all 101 games |
| exact_statistics-004 | `+6.33` | 6.33 | 6.329268292682927 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date` | BINDING | "average margin ... points per game" bound as points per game |
| exact_statistics-006 | `23` | 23 | 23 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (away_team_id='NYK') order by game_date` | BINDING | phase follows the number; the audit used all away games |
| exact_statistics-006 | `42` | 42 | 42 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (away_team_id='NYK') order by game_date` | BINDING | phase follows the number; the audit used all away games |
| exact_statistics-007 | `29` | 29 | 29 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date` | BINDING | "lost 29 games" bound to all-game losses |
| date_range_last_n-005 | `18-9` | '18-9' | '18-9' | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-02-19') order by game_date` | BINDING | post-All-Star-break window not modeled |
| date_range_last_n-005 | `27` | 27 | 27 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-02-19') order by game_date` | BINDING | post-All-Star-break window not modeled |
| date_range_last_n-005 | `113.26` | 113.26 | 113.25925925925925 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-02-19') order by game_date` | BINDING | post-All-Star-break window not modeled |
| comparisons-001 | `40` | 40 | 40 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (home_team_id='NYK') order by game_date` | BINDING | home clause inherited the question's "on the road" location |
| comparisons-001 | `119.00` | 119.0 | 119.0 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (home_team_id='NYK') order by game_date` | BINDING | home clause inherited the question's "on the road" location |
| comparisons-001 | `108.97` | 108.97 | 108.975 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (home_team_id='NYK') order by game_date` | BINDING | home clause inherited the question's "on the road" location |
| comparisons-001 | `+10.03` | 10.03 | 10.025 | `games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (home_team_id='NYK') order by game_date` | BINDING | home clause inherited the question's "on the road" location |
| turning_points-005 | `8-0` | '8-0' | '8-0 Q2 00:08 to Q3 10:47' | `select sequence, period, clock, team_id, home_score, away_score from game_events where game_id=69 and sequence between 214 and 230 order by sequence` | BINDING | run attributed to GSW by nearby text; the snapshots identify a NYK run |
| unsupported-008 | `26.0` | 26.0 | 26.04054054054054 | `player_game_stats where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 and g.season_type='regular' order by g.game_date` | BINDING | phase follows the number and was not applied |
| unsupported-008 | `74` | 74.0 | 74 | `player_game_stats where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 and g.season_type='regular' order by g.game_date` | BINDING | phase follows the number and was not applied |

## Start-clock proof

The three play-by-play rows that decide the disputed clocks, recomputed from `game_events`

```sql
-- 8-0 Knicks run, 2026-03-15 vs GSW (game 69): start clock Q2 00:08, start score 42-54
select sequence, period, clock, team_id, home_score, away_score
from game_events where game_id=69 and sequence between 214 and 230 order by sequence;
-- 214 Q2 00:54 GSW 42-54 | 220 Q2 00:08 NYK 45-54 | 227 Q3 11:24 NYK 48-54 | 230 Q3 10:47 NYK 50-54
-- Knicks 3+3+2 = 8 unanswered; start Q2 00:08, end Q3 10:47. Correct.

-- 83-104 at Q4 08:32, 2026-03-26 at CHA (game 74): Knicks 83, Charlotte 104, deficit 21
select sequence, period, clock, team_id, home_score, away_score from game_events
where game_id=74 and period=4 and clock='08:32';
-- 320 Q4 08:32 CHA 104-83 (home CHA). Deficit 21. Correct.

-- 7-0 Knicks run, 2026-01-28 vs TOR (game 47): start clock Q3 07:46, start score 55-66
select sequence, period, clock, team_id, home_score, away_score
from game_events where game_id=47 and sequence between 287 and 299 order by sequence;
-- 287 Q3 08:00 TOR 66-55 | 288 Q3 07:46 NYK 66-57 | 290 Q3 07:33 NYK 66-60 | 299 Q3 06:36 NYK 66-62
-- Knicks 2+3+2 = 7 unanswered; 55-66 to 62-66. Correct.
```

So the three "wrong start clock" suspicions are labelled `BINDING` on SQL evidence, not kept as REAL.

## Coverage before and after

Checked coverage counts verified plus wrong over found; unverified atoms are never counted as passes.

| set | found | verified before | wrong before | unverified before | coverage before | verified after | wrong after | unverified after | coverage after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| final trial 1 | 523 | 515 | 8 | 0 | 100.0% | 515 | 8 | 0 | 100.0% |
| final trial 2 | 465 | 413 | 9 | 43 | 90.8% | 424 | 9 | 32 | 93.1% |
| correctness acceptance | 124 | 108 | 0 | 16 | 87.1% | 124 | 0 | 0 | 100.0% |
| w4-bench trial 1 | 597 | 320 | 21 | 256 | 57.1% | 384 | 0 | 213 | 64.3% |
| w4-bench trial 2 | 644 | 432 | 15 | 197 | 69.4% | 477 | 0 | 167 | 74.1% |

The final sets keep exactly their pre-existing wrong atoms (no regression). The acceptance set gains 16
verifications and now checks every atom. Both w4-bench trials lose every wrong atom and gain 64 and 45 verifications.

## Remaining real wrong numbers (release blockers)

The w4-bench trials and the acceptance set now have zero wrong numbers. The older `final/` record still
contains three wrong responses, unchanged by this work and not caused by binding:

| set | id | delivered | SQL recomputation |
| --- | --- | --- | --- |
| final trial 1+2 | date_range_last_n-009 | 10 wins and 6 losses over 16 games for March 1-15 | 6-3 over 9 games |
| final trial 1+2 | date_range_last_n-010 | 53 wins and 29 losses over 82 games for the first 10 games | 7-3 over 10 games |
| final trial 2 | comparisons-002 | 39 called Towns' highest observed scoring output | maximum 40 |

These are genuine wrong statements, not audit artifacts; they stay release blockers for any release that
uses the `final/` response record. The zero-wrong-numbers gate on the w4-bench trials is now decidable:
0 wrong; 213 and 167 atoms remain unverified and are reported as unverified (not passes), not mislabelled.

## One-command rerun

```sh
./run.sh
```

It regenerates `trial1/`, `trial2/`, `acceptance/`, `w4-trial1/` and `w4-trial2/` from the five recorded
response sets and prints found/verified/wrong/unverified per set. It needs the local restore container
`kiq-integrate-postgres-1` (override with `KIQ_PSQL`).

