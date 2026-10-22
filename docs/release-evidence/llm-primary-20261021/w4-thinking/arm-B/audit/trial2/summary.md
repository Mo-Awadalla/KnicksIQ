# Replacement factual audit: arm B trial 2

Responses: 30. Numeric atoms found: 248. Checked: 150 (60.48% coverage). Verified: 146. Wrong: 4. Unverified: 98.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-002 | 1 | 16 | 7 | 0 | 9 | 44% | UNVERIFIED | n/a |
| aliases_typos-003 | 1 | 31 | 11 | 0 | 20 | 35% | UNVERIFIED | n/a |
| comparisons-001 | 1 | 10 | 10 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-002 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-003 | 1 | 9 | 7 | 0 | 2 | 78% | UNVERIFIED | n/a |
| comparisons-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-007 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-010 | 1 | 4 | 0 | 2 | 2 | 50% | INCORRECT | n/a |
| date_range_last_n-001 | 1 | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-003 | 1 | 9 | 1 | 0 | 8 | 11% | UNVERIFIED | n/a |
| date_range_last_n-005 | 1 | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-008 | 1 | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-001 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-002 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-003 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-001 | 1 | 12 | 5 | 1 | 6 | 50% | INCORRECT | n/a |
| single_game_narrative-002 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-003 | 1 | 58 | 13 | 0 | 45 | 22% | UNVERIFIED | n/a |
| single_game_narrative-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-009 | 1 | 8 | 8 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-001 | 1 | 7 | 2 | 1 | 4 | 43% | INCORRECT | n/a |
| turning_points-002 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| turning_points-003 | 1 | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| unsupported-001 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-002 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-003 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-004 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 3 | 52 | 23 | 0 | 29 | 44% |
| comparisons | 6 | 27 | 21 | 2 | 4 | 85% |
| date_range_last_n | 5 | 28 | 20 | 0 | 8 | 71% |
| exact_statistics | 3 | 12 | 12 | 0 | 0 | 100% |
| single_game_narrative | 5 | 78 | 26 | 1 | 51 | 35% |
| turning_points | 3 | 50 | 43 | 1 | 6 | 88% |
| unsupported | 5 | 1 | 1 | 0 | 0 | 100% |

## Wrong numbers (4)

### single_game_narrative-001 (trial 1)

- `12-0` claimed; expected `0-1` (team record {'season_type': 'regular', 'opp': 'BOS', 'loc': None, 'start': '2025-12-02', 'end': '2025-12-02', 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (((home_team_id='NYK' and away_team_id='BOS') or (away_team_id='NYK' and home_team_id='BOS'))) and (game_date >= '2025-12-02') and (game_date <= '2025-12-02') order by game_date
  ```

### turning_points-001 (trial 1)

- `17-0` claimed; expected `no matching run` (BOS run).

  ```sql
  select ... game_events
  ```

### comparisons-010 (trial 1)

- `121.75` claimed; expected `120.71014492753623` (points per game {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': 'W'}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and ((home_team_id='NYK' and home_score>away_score) or (away_team_id='NYK' and away_score>home_score)) order by game_date
  ```

- `106.76` claimed; expected `120.71014492753623` (points per game {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': 'W'}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and ((home_team_id='NYK' and home_score>away_score) or (away_team_id='NYK' and away_score>home_score)) order by game_date
  ```


## Unverified numbers (98)

- aliases_typos-002: 9 unverified: `32`, `105`, `95`, `123`, `117`, `111`, `89`, `112`, `106`
- aliases_typos-003: 20 unverified: `42`, `8`, `9`, `5`, `40`, `5`, `8`, `1`, `40`, `4`, `8`, `2` (+8 more)
- comparisons-003: 2 unverified: `+19.60`, `+8.00`
- comparisons-010: 2 unverified: `53-0`, `0-29`
- date_range_last_n-003: 8 unverified: `5`, `32.6`, `30`, `20`, `32`, `36`, `45`, `45`
- single_game_narrative-001: 6 unverified: `Q2 11:07`, `37-23`, `Q2 10:07`, `Q2 08:25`, `39-25`, `39-37`
- single_game_narrative-003: 45 unverified: `12-27`, `30-36`, `-6`, `128-125`, `+3`, `01-02`, `29-17`, `+12`, `99-111`, `-12`, `04-06`, `27-26` (+33 more)
- turning_points-001: 4 unverified: `Q2 07:29`, `Q2 03:49`, `33-36`, `50-36`
- turning_points-003: 2 unverified: `26`, `26`
