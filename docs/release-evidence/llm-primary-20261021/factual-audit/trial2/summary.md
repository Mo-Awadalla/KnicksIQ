# Replacement factual audit: 16000 trial 2

Responses: 70. Numeric atoms found: 465. Checked: 433 (93.12% coverage). Verified: 424. Wrong: 9. Unverified: 32.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 |  | 13 | 13 | 0 | 0 | 100% | CORRECT | CORRECT |
| aliases_typos-002 |  | 17 | 13 | 0 | 4 | 76% | UNVERIFIED | CORRECT |
| aliases_typos-003 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | UNSUPPORTED_CLAIM |
| aliases_typos-004 |  | 21 | 21 | 0 | 0 | 100% | CORRECT | CORRECT |
| aliases_typos-005 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | DECLINE_MISSED_ANSWER |
| aliases_typos-006 |  | 7 | 7 | 0 | 0 | 100% | CORRECT | CORRECT |
| aliases_typos-007 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| aliases_typos-008 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | DECLINE_MISSED_ANSWER |
| aliases_typos-009 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| aliases_typos-010 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | INCORRECT |
| comparisons-001 |  | 11 | 11 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| comparisons-002 |  | 17 | 16 | 1 | 0 | 100% | INCORRECT | CORRECT |
| comparisons-003 |  | 9 | 7 | 0 | 2 | 78% | UNVERIFIED | DECLINE_MISSED_ANSWER |
| comparisons-004 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| comparisons-005 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| comparisons-006 |  | 10 | 10 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| comparisons-007 |  | 33 | 32 | 0 | 1 | 97% | UNVERIFIED | UNSUPPORTED_CLAIM |
| comparisons-008 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | CORRECT |
| comparisons-009 |  | 21 | 21 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| comparisons-010 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| date_range_last_n-001 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | CORRECT |
| date_range_last_n-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | CORRECT |
| date_range_last_n-003 |  | 9 | 9 | 0 | 0 | 100% | CORRECT | CORRECT |
| date_range_last_n-004 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | CORRECT |
| date_range_last_n-005 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| date_range_last_n-006 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| date_range_last_n-007 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| date_range_last_n-008 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| date_range_last_n-009 |  | 4 | 0 | 4 | 0 | 100% | INCORRECT | DECLINE_MISSED_ANSWER |
| date_range_last_n-010 |  | 4 | 0 | 4 | 0 | 100% | INCORRECT | DECLINE_MISSED_ANSWER |
| exact_statistics-001 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-002 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-003 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-004 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-005 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-006 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-007 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-008 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-009 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-010 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| single_game_narrative-001 |  | 11 | 9 | 0 | 2 | 82% | UNVERIFIED | DECLINE_MISSED_ANSWER |
| single_game_narrative-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | CORRECT |
| single_game_narrative-003 |  | 41 | 38 | 0 | 3 | 93% | UNVERIFIED | DECLINE_MISSED_ANSWER |
| single_game_narrative-004 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | INSUFFICIENT |
| single_game_narrative-005 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| single_game_narrative-006 |  | 10 | 10 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| single_game_narrative-007 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| single_game_narrative-008 |  | 1 | 0 | 0 | 1 | 0% | UNVERIFIED | DECLINE_MISSED_ANSWER |
| single_game_narrative-009 |  | 8 | 8 | 0 | 0 | 100% | CORRECT | CORRECT |
| single_game_narrative-010 |  | 9 | 6 | 0 | 3 | 67% | UNVERIFIED | DECLINE_APPROPRIATE |
| turning_points-001 |  | 9 | 3 | 0 | 6 | 33% | UNVERIFIED | DECLINE_MISSED_ANSWER |
| turning_points-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | CORRECT |
| turning_points-003 |  | 9 | 7 | 0 | 2 | 78% | UNVERIFIED | DECLINE_MISSED_ANSWER |
| turning_points-004 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| turning_points-005 |  | 11 | 11 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| turning_points-006 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| turning_points-007 |  | 15 | 11 | 0 | 4 | 73% | UNVERIFIED | DECLINE_MISSED_ANSWER |
| turning_points-008 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| turning_points-009 |  | 15 | 15 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| turning_points-010 |  | 8 | 8 | 0 | 0 | 100% | CORRECT | CORRECT |
| unsupported-001 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | DECLINE_APPROPRIATE |
| unsupported-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | DECLINE_APPROPRIATE |
| unsupported-003 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | DECLINE_APPROPRIATE |
| unsupported-004 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | DECLINE_APPROPRIATE |
| unsupported-005 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | DECLINE_APPROPRIATE |
| unsupported-006 |  | 9 | 5 | 0 | 4 | 56% | UNVERIFIED | DECLINE_APPROPRIATE |
| unsupported-007 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | DECLINE_APPROPRIATE |
| unsupported-008 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | UNSUPPORTED_CLAIM |
| unsupported-009 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | CORRECT |
| unsupported-010 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 10 | 70 | 66 | 0 | 4 | 94% |
| comparisons | 10 | 115 | 111 | 1 | 3 | 97% |
| date_range_last_n | 10 | 48 | 40 | 8 | 0 | 100% |
| exact_statistics | 10 | 37 | 37 | 0 | 0 | 100% |
| single_game_narrative | 10 | 89 | 80 | 0 | 9 | 90% |
| turning_points | 10 | 84 | 72 | 0 | 12 | 86% |
| unsupported | 10 | 22 | 18 | 0 | 4 | 82% |

## Wrong numbers (9)

### date_range_last_n-009 (trial n/a)

- `10` claimed; expected `6` (wins {'season_type': 'regular', 'opp': None, 'loc': None, 'start': '2026-03-01', 'end': '2026-03-15', 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-03-01') and (game_date <= '2026-03-15') order by game_date
  ```

- `16` claimed; expected `9` (games {'season_type': 'regular', 'opp': None, 'loc': None, 'start': '2026-03-01', 'end': '2026-03-15', 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-03-01') and (game_date <= '2026-03-15') order by game_date
  ```

- `6` claimed; expected `3` (losses {'season_type': 'regular', 'opp': None, 'loc': None, 'start': '2026-03-01', 'end': '2026-03-15', 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-03-01') and (game_date <= '2026-03-15') order by game_date
  ```

- `16` claimed; expected `9` (games {'season_type': 'regular', 'opp': None, 'loc': None, 'start': '2026-03-01', 'end': '2026-03-15', 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (game_date >= '2026-03-01') and (game_date <= '2026-03-15') order by game_date
  ```

### date_range_last_n-010 (trial n/a)

- `53` claimed; expected `7` (wins {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': 10, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date asc limit 10
  ```

- `82` claimed; expected `10` (games {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': 10, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date asc limit 10
  ```

- `29` claimed; expected `3` (losses {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': 10, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date asc limit 10
  ```

- `82` claimed; expected `10` (games {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': 10, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date asc limit 10
  ```

### comparisons-002 (trial n/a)

- `39` claimed; expected `40` (Karl-Anthony Towns maximum single-game points).

  ```sql
  select g.game_date, g.id, s.points, s.rebounds, s.assists, s.turnovers from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name='Karl-Anthony Towns' and s.minutes > 0 order by g.game_date
  ```


## Unverified numbers (32)

- aliases_typos-002: 4 unverified: `123`, `117`, `112`, `106`
- comparisons-003: 2 unverified: `105`, `95`
- comparisons-007: 1 unverified: `3:26`
- single_game_narrative-001: 2 unverified: `37-23`, `Q2 11:07`
- single_game_narrative-003: 3 unverified: `5`, `10`, `22`
- single_game_narrative-008: 1 unverified: `19.6`
- single_game_narrative-010: 3 unverified: `125-135`, `125`, `105`
- turning_points-001: 6 unverified: `17-0`, `Q2 07:29`, `Q2 03:49`, `33-36`, `50-36`, `12-0`
- turning_points-003: 2 unverified: `9`, `128-125`
- turning_points-007: 4 unverified: `70-84`, `87-84`, `67-77`, `82-77`
- unsupported-006: 4 unverified: `8`, `0`, `35`, `18`
