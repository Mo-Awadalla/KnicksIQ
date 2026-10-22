# Replacement factual audit: w4-failed head responses

Responses: 8. Numeric atoms found: 94. Checked: 62 (65.96% coverage). Verified: 58. Wrong: 4. Unverified: 32.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-003 |  | 21 | 5 | 0 | 16 | 24% | UNVERIFIED | n/a |
| comparisons-002 |  | 5 | 1 | 0 | 4 | 20% | UNVERIFIED | n/a |
| comparisons-008 |  | 5 | 1 | 1 | 3 | 40% | INCORRECT | n/a |
| comparisons-010 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| date_range_last_n-005 |  | 6 | 1 | 2 | 3 | 50% | INCORRECT | n/a |
| single_game_narrative-004 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-003 |  | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| turning_points-007 |  | 10 | 5 | 1 | 4 | 60% | INCORRECT | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 1 | 21 | 5 | 0 | 16 | 24% |
| comparisons | 3 | 10 | 2 | 1 | 7 | 30% |
| date_range_last_n | 1 | 6 | 1 | 2 | 3 | 50% |
| single_game_narrative | 1 | 4 | 4 | 0 | 0 | 100% |
| turning_points | 2 | 53 | 46 | 1 | 6 | 89% |

## Wrong numbers (4)

### date_range_last_n-005 (trial n/a)

- `27` claimed; expected `82` (game count {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `113.26` claimed; expected `116.45121951219512` (points per game {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

### comparisons-008 (trial n/a)

- `75` claimed; expected `82` (game count {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

### turning_points-007 (trial n/a)

- `15-0` claimed; expected `no matching run` (NYK run).

  ```sql
  select ... game_events
  ```


## Unverified numbers (32)

- aliases_typos-003: 16 unverified: `47`, `3`, `8`, `0`, `42`, `8`, `9`, `5`, `40`, `5`, `8`, `1` (+4 more)
- comparisons-002: 4 unverified: `26.0`, `74`, `20.1`, `75`
- comparisons-008: 3 unverified: `11.9`, `7.4`, `66`
- date_range_last_n-005: 3 unverified: `18-9`, `106.59`, `+6.67`
- turning_points-003: 2 unverified: `26`, `26`
- turning_points-007: 4 unverified: `Q3 03:57`, `Q4 11:39`, `77-67`, `77-82`
