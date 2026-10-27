# Replacement factual audit: arm A trial 1

Responses: 30. Numeric atoms found: 203. Checked: 134 (66.01% coverage). Verified: 130. Wrong: 4. Unverified: 69.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 |  | 9 | 7 | 0 | 2 | 78% | UNVERIFIED | n/a |
| aliases_typos-002 |  | 15 | 6 | 0 | 9 | 40% | UNVERIFIED | n/a |
| aliases_typos-003 |  | 5 | 1 | 0 | 4 | 20% | UNVERIFIED | n/a |
| comparisons-001 |  | 10 | 10 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-003 |  | 20 | 20 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-007 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-010 |  | 4 | 0 | 3 | 1 | 75% | INCORRECT | n/a |
| date_range_last_n-001 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-003 |  | 4 | 2 | 0 | 2 | 50% | UNVERIFIED | n/a |
| date_range_last_n-005 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-008 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-001 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-002 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-003 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| single_game_narrative-001 |  | 16 | 14 | 1 | 1 | 94% | INCORRECT | n/a |
| single_game_narrative-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-003 |  | 58 | 13 | 0 | 45 | 22% | UNVERIFIED | n/a |
| single_game_narrative-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-009 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| turning_points-001 |  | 7 | 7 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| turning_points-003 |  | 19 | 15 | 0 | 4 | 79% | UNVERIFIED | n/a |
| unsupported-001 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-003 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-004 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-006 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 3 | 29 | 14 | 0 | 15 | 48% |
| comparisons | 6 | 34 | 30 | 3 | 1 | 97% |
| date_range_last_n | 5 | 21 | 19 | 0 | 2 | 90% |
| exact_statistics | 3 | 12 | 11 | 0 | 1 | 92% |
| single_game_narrative | 5 | 79 | 32 | 1 | 46 | 42% |
| turning_points | 3 | 26 | 22 | 0 | 4 | 85% |
| unsupported | 5 | 2 | 2 | 0 | 0 | 100% |

## Wrong numbers (4)

### single_game_narrative-001 (trial n/a)

- `18` claimed; expected `None` (comeback).

  ```sql
  select ... game_events
  ```

### comparisons-010 (trial n/a)

- `121.75` claimed; expected `120.71014492753623` (points per game {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': 'W'}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and ((home_team_id='NYK' and home_score>away_score) or (away_team_id='NYK' and away_score>home_score)) order by game_date
  ```

- `53` claimed; expected `69` (game count {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': 'W'}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and ((home_team_id='NYK' and home_score>away_score) or (away_team_id='NYK' and away_score>home_score)) order by game_date
  ```

- `29` claimed; expected `0` (losses {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': 'W'}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and ((home_team_id='NYK' and home_score>away_score) or (away_team_id='NYK' and away_score>home_score)) order by game_date
  ```


## Unverified numbers (69)

- aliases_typos-001: 2 unverified: `3-1`, `+8.0`
- aliases_typos-002: 9 unverified: `+32`, `105`, `95`, `123`, `117`, `111`, `89`, `112`, `106`
- aliases_typos-003: 4 unverified: `47`, `3`, `8`, `0`
- comparisons-010: 1 unverified: `106.76`
- date_range_last_n-003: 2 unverified: `5`, `32.6`
- exact_statistics-003: 1 unverified: `+6.33`
- single_game_narrative-001: 1 unverified: `117-123`
- single_game_narrative-003: 45 unverified: `12-27`, `30-36`, `-6`, `128-125`, `+3`, `01-02`, `29-17`, `+12`, `99-111`, `-12`, `04-06`, `27-26` (+33 more)
- turning_points-003: 4 unverified: `78-64`, `6:56`, `0:33`, `99-111`
