# Replacement factual audit: final-go trial 1

Responses: 70. Numeric atoms found: 635. Checked: 424 (66.77% coverage). Verified: 418. Wrong: 6. Unverified: 211.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-002 |  | 16 | 12 | 0 | 4 | 75% | UNVERIFIED | n/a |
| aliases_typos-003 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-004 |  | 23 | 1 | 1 | 21 | 9% | INCORRECT | n/a |
| aliases_typos-005 |  | 8 | 5 | 2 | 1 | 88% | INCORRECT | n/a |
| aliases_typos-006 |  | 14 | 11 | 0 | 3 | 79% | UNVERIFIED | n/a |
| aliases_typos-007 |  | 13 | 1 | 0 | 12 | 8% | UNVERIFIED | n/a |
| aliases_typos-008 |  | 46 | 17 | 0 | 29 | 37% | UNVERIFIED | n/a |
| aliases_typos-009 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-010 |  | 13 | 10 | 0 | 3 | 77% | UNVERIFIED | n/a |
| comparisons-001 |  | 10 | 10 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-002 |  | 5 | 1 | 1 | 3 | 40% | INCORRECT | n/a |
| comparisons-003 |  | 20 | 20 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-004 |  | 10 | 4 | 0 | 6 | 40% | UNVERIFIED | n/a |
| comparisons-005 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-007 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-008 |  | 7 | 1 | 0 | 6 | 14% | UNVERIFIED | n/a |
| comparisons-009 |  | 22 | 6 | 0 | 16 | 27% | UNVERIFIED | n/a |
| comparisons-010 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| date_range_last_n-001 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-002 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-003 |  | 9 | 3 | 0 | 6 | 33% | UNVERIFIED | n/a |
| date_range_last_n-004 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-005 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-006 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-007 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-008 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-009 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-010 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-001 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-002 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-003 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-004 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-005 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-006 |  | 6 | 5 | 0 | 1 | 83% | UNVERIFIED | n/a |
| exact_statistics-007 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-008 |  | 4 | 2 | 0 | 2 | 50% | UNVERIFIED | n/a |
| exact_statistics-009 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-010 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-001 |  | 16 | 14 | 1 | 1 | 94% | INCORRECT | n/a |
| single_game_narrative-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-003 |  | 58 | 13 | 0 | 45 | 22% | UNVERIFIED | n/a |
| single_game_narrative-004 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-005 |  | 37 | 2 | 0 | 35 | 5% | UNVERIFIED | n/a |
| single_game_narrative-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-007 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-008 |  | 28 | 28 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-009 |  | 8 | 8 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-010 |  | 8 | 5 | 0 | 3 | 62% | UNVERIFIED | n/a |
| turning_points-001 |  | 9 | 8 | 0 | 1 | 89% | UNVERIFIED | n/a |
| turning_points-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-003 |  | 17 | 16 | 0 | 1 | 94% | UNVERIFIED | n/a |
| turning_points-004 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-005 |  | 13 | 12 | 0 | 1 | 92% | UNVERIFIED | n/a |
| turning_points-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| turning_points-007 |  | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| turning_points-008 |  | 30 | 20 | 1 | 9 | 70% | INCORRECT | n/a |
| turning_points-009 |  | 28 | 28 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-010 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-001 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-003 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-004 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-005 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-006 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-007 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-008 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-009 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-010 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 10 | 145 | 69 | 3 | 73 | 50% |
| comparisons | 10 | 78 | 46 | 1 | 31 | 60% |
| date_range_last_n | 10 | 49 | 43 | 0 | 6 | 88% |
| exact_statistics | 10 | 38 | 35 | 0 | 3 | 92% |
| single_game_narrative | 10 | 168 | 83 | 1 | 84 | 50% |
| turning_points | 10 | 149 | 134 | 1 | 14 | 91% |
| unsupported | 10 | 8 | 8 | 0 | 0 | 100% |

## Wrong numbers (6)

### comparisons-002 (trial n/a)

- `74` claimed; expected `75` (Karl-Anthony Towns appearances {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select g.game_date, g.id, s.points, s.rebounds, s.assists, s.turnovers from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name='Karl-Anthony Towns' and s.minutes > 0 and g.season_type='regular' order by g.game_date
  ```

### single_game_narrative-001 (trial n/a)

- `18` claimed; expected `None` (comeback).

  ```sql
  select ... game_events
  ```

### turning_points-008 (trial n/a)

- `3-0` claimed; expected `no matching run` (CHA run).

  ```sql
  select ... game_events
  ```

### aliases_typos-004 (trial n/a)

- `8` claimed; expected `575` (team points {'season_type': 'regular', 'opp': 'TOR', 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (((home_team_id='NYK' and away_team_id='TOR') or (away_team_id='NYK' and home_team_id='TOR'))) order by game_date
  ```

### aliases_typos-005 (trial n/a)

- `Q1 05:53` claimed; expected `Q1 01:01` (run end clock 2025-12-05).

  ```sql
  select ... game_events
  ```

- `23-0` claimed; expected `no matching run` (NYK run).

  ```sql
  select ... game_events
  ```


## Unverified numbers (211)

- aliases_typos-002: 4 unverified: `123`, `117`, `112`, `106`
- aliases_typos-004: 21 unverified: `17.4`, `5`, `22`, `11`, `30`, `14`, `16`, `12`, `9`, `22`, `1`, `28` (+9 more)
- aliases_typos-005: 1 unverified: `Q1 09:14`
- aliases_typos-006: 3 unverified: `+11.00`, `-2.00`, `+17.50`
- aliases_typos-007: 12 unverified: `10-31`, `34-35`, `-1`, `11-02`, `23-27`, `-4`, `02-22`, `22-21`, `+1`, `04-03`, `28-24`, `+4`
- aliases_typos-008: 29 unverified: `16.6`, `14`, `3`, `3`, `2`, `2`, `+17`, `33`, `15`, `5`, `4`, `2` (+17 more)
- aliases_typos-010: 3 unverified: `19`, `43`, `110-107`
- comparisons-002: 3 unverified: `26.0`, `20.1`, `75`
- comparisons-004: 6 unverified: `7-3`, `121.8`, `112.7`, `6-4`, `111.2`, `108.3`
- comparisons-008: 6 unverified: `11.9`, `75`, `889`, `7.4`, `66`, `486`
- comparisons-009: 16 unverified: `2375`, `28.96`, `2307`, `28.13`, `+68`, `37-5`, `-40`, `2316`, `28.24`, `2078`, `25.34`, `+238` (+4 more)
- date_range_last_n-003: 6 unverified: `32.6`, `30`, `20`, `32`, `36`, `45`
- exact_statistics-006: 1 unverified: `+118`
- exact_statistics-008: 2 unverified: `54`, `120-66`
- single_game_narrative-001: 1 unverified: `117-123`
- single_game_narrative-003: 45 unverified: `12-27`, `30-36`, `-6`, `128-125`, `+3`, `01-02`, `29-17`, `+12`, `99-111`, `-12`, `04-06`, `27-26` (+33 more)
- single_game_narrative-005: 35 unverified: `1`, `56.0-54.0`, `2`, `55.75-53.25`, `2`, `1 -0.25`, `-1`, `2`, `2`, `0`, `0`, `11-26` (+23 more)
- single_game_narrative-010: 3 unverified: `128-116`, `105-99`, `136-96`
- turning_points-001: 1 unverified: `12-0`
- turning_points-003: 1 unverified: `99-111`
- turning_points-005: 1 unverified: `48-27`
- turning_points-007: 2 unverified: `43`, `43`
- turning_points-008: 9 unverified: `21`, `21`, `21`, `Q1 10:26`, `129-101`, `2-8`, `Q1 10:20`, `Q1 08:16`, `11-11`
