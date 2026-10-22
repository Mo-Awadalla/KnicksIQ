# Replacement factual audit: w4-bench trial 2

Responses: 70. Numeric atoms found: 644. Checked: 447 (69.41% coverage). Verified: 432. Wrong: 15. Unverified: 197.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 | 1 | 5 | 3 | 0 | 2 | 60% | UNVERIFIED | n/a |
| aliases_typos-002 | 1 | 12 | 9 | 0 | 3 | 75% | UNVERIFIED | n/a |
| aliases_typos-003 | 1 | 15 | 7 | 0 | 8 | 47% | UNVERIFIED | n/a |
| aliases_typos-004 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-005 | 1 | 7 | 7 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-006 | 1 | 16 | 11 | 0 | 5 | 69% | UNVERIFIED | n/a |
| aliases_typos-007 | 1 | 23 | 4 | 0 | 19 | 17% | UNVERIFIED | n/a |
| aliases_typos-008 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-009 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-010 | 1 | 43 | 40 | 0 | 3 | 93% | UNVERIFIED | n/a |
| comparisons-001 | 1 | 10 | 4 | 4 | 2 | 80% | INCORRECT | n/a |
| comparisons-002 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-003 | 1 | 9 | 3 | 0 | 6 | 33% | UNVERIFIED | n/a |
| comparisons-004 | 1 | 13 | 6 | 0 | 7 | 46% | UNVERIFIED | n/a |
| comparisons-005 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-007 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-008 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-009 | 1 | 22 | 6 | 0 | 16 | 27% | UNVERIFIED | n/a |
| comparisons-010 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| date_range_last_n-001 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-003 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-004 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| date_range_last_n-005 | 1 | 6 | 1 | 3 | 2 | 67% | INCORRECT | n/a |
| date_range_last_n-006 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-007 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-008 | 1 | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-009 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-010 | 1 | 6 | 5 | 0 | 1 | 83% | UNVERIFIED | n/a |
| exact_statistics-001 | 1 | 5 | 4 | 0 | 1 | 80% | UNVERIFIED | n/a |
| exact_statistics-002 | 1 | 3 | 1 | 1 | 1 | 67% | INCORRECT | n/a |
| exact_statistics-003 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-004 | 1 | 3 | 1 | 1 | 1 | 67% | INCORRECT | n/a |
| exact_statistics-005 | 1 | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| exact_statistics-006 | 1 | 4 | 1 | 2 | 1 | 75% | INCORRECT | n/a |
| exact_statistics-007 | 1 | 4 | 3 | 1 | 0 | 100% | INCORRECT | n/a |
| exact_statistics-008 | 1 | 8 | 4 | 0 | 4 | 50% | UNVERIFIED | n/a |
| exact_statistics-009 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-010 | 1 | 3 | 2 | 0 | 1 | 67% | UNVERIFIED | n/a |
| single_game_narrative-001 | 1 | 44 | 42 | 0 | 2 | 95% | UNVERIFIED | n/a |
| single_game_narrative-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-003 | 1 | 71 | 21 | 0 | 50 | 30% | UNVERIFIED | n/a |
| single_game_narrative-004 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-005 | 1 | 37 | 2 | 0 | 35 | 5% | UNVERIFIED | n/a |
| single_game_narrative-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-007 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-008 | 1 | 28 | 28 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-009 | 1 | 8 | 8 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-010 | 1 | 6 | 4 | 0 | 2 | 67% | UNVERIFIED | n/a |
| turning_points-001 | 1 | 10 | 4 | 0 | 6 | 40% | UNVERIFIED | n/a |
| turning_points-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-003 | 1 | 16 | 12 | 0 | 4 | 75% | UNVERIFIED | n/a |
| turning_points-004 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| turning_points-005 | 1 | 13 | 5 | 1 | 7 | 46% | INCORRECT | n/a |
| turning_points-006 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-007 | 1 | 43 | 40 | 0 | 3 | 93% | UNVERIFIED | n/a |
| turning_points-008 | 1 | 50 | 47 | 0 | 3 | 94% | UNVERIFIED | n/a |
| turning_points-009 | 1 | 15 | 14 | 0 | 1 | 93% | UNVERIFIED | n/a |
| turning_points-010 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-001 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-002 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-003 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-004 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-005 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-006 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-007 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-008 | 1 | 3 | 1 | 2 | 0 | 100% | INCORRECT | n/a |
| unsupported-009 | 1 | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-010 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 10 | 130 | 90 | 0 | 40 | 69% |
| comparisons | 10 | 62 | 27 | 4 | 31 | 50% |
| date_range_last_n | 10 | 40 | 34 | 3 | 3 | 92% |
| exact_statistics | 10 | 42 | 27 | 5 | 10 | 76% |
| single_game_narrative | 10 | 207 | 118 | 0 | 89 | 57% |
| turning_points | 10 | 156 | 131 | 1 | 24 | 85% |
| unsupported | 10 | 7 | 5 | 2 | 0 | 100% |

## Wrong numbers (15)

### exact_statistics-002 (trial 1)

- `9,549` claimed; expected `11750` (team points {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

### exact_statistics-004 (trial 1)

- `+6.33` claimed; expected `116.45121951219512` (points per game {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

### exact_statistics-006 (trial 1)

- `23` claimed; expected `32` (wins {'season_type': None, 'opp': None, 'loc': 'away', 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (away_team_id='NYK') order by game_date
  ```

- `42` claimed; expected `52` (games {'season_type': None, 'opp': None, 'loc': 'away', 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (away_team_id='NYK') order by game_date
  ```

### exact_statistics-007 (trial 1)

- `29` claimed; expected `32` (games {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

### date_range_last_n-005 (trial 1)

- `18-9` claimed; expected `53-29` (team record {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `27` claimed; expected `82` (game count {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `113.26` claimed; expected `116.45121951219512` (points per game {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

### comparisons-001 (trial 1)

- `40` claimed; expected `42` (game count {'season_type': 'regular', 'opp': None, 'loc': 'away', 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (away_team_id='NYK') order by game_date
  ```

- `119.00` claimed; expected `114.02380952380952` (points for/against per game).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (away_team_id='NYK') order by game_date
  ```

- `108.97` claimed; expected `111.21428571428571` (points for/against per game).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (away_team_id='NYK') order by game_date
  ```

- `+10.03` claimed; expected `2.8095238095238093` (average margin {'season_type': 'regular', 'opp': None, 'loc': 'away', 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (away_team_id='NYK') order by game_date
  ```

### turning_points-005 (trial 1)

- `8-0` claimed; expected `no matching run` (GSW run).

  ```sql
  select ... game_events
  ```

### unsupported-008 (trial 1)

- `26.0` claimed; expected `26.516129032258064` (Jalen Brunson points per appearance {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select g.game_date, g.id, s.points, s.rebounds, s.assists, s.turnovers from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 order by g.game_date
  ```

- `74` claimed; expected `93` (Jalen Brunson points per appearance {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select g.game_date, g.id, s.points, s.rebounds, s.assists, s.turnovers from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 order by g.game_date
  ```


## Unverified numbers (197)

- aliases_typos-001: 2 unverified: `103.25`, `+8.0`
- aliases_typos-002: 3 unverified: `117-123`, `111-89`, `112-106`
- aliases_typos-003: 8 unverified: `42`, `8`, `9`, `5`, `40`, `5`, `8`, `1`
- aliases_typos-006: 5 unverified: `104.78`, `2-1`, `-2.00`, `4-2`, `+17.50`
- aliases_typos-007: 19 unverified: `4`, `10`, `31`, `34-35`, `-1`, `11`, `2`, `23-27`, `-4`, `2`, `22`, `22-21` (+7 more)
- aliases_typos-010: 3 unverified: `43`, `80-118`, `43`
- comparisons-001: 2 unverified: `30-10`, `23-19`
- comparisons-003: 6 unverified: `111.25`, `103.25`, `+8.00`, `115.00`, `95.40`, `+19.60`
- comparisons-004: 7 unverified: `7-3`, `112.7`, `6-4`, `111.2`, `108.3`, `+9.1`, `+2.9`
- comparisons-009: 16 unverified: `2375`, `28.96`, `2307`, `28.13`, `+68`, `37-5`, `-40`, `2316`, `28.24`, `2078`, `25.34`, `+238` (+4 more)
- date_range_last_n-005: 2 unverified: `106.59`, `+6.67`
- date_range_last_n-010: 1 unverified: `112.7`
- exact_statistics-001: 1 unverified: `+519`
- exact_statistics-002: 1 unverified: `82`
- exact_statistics-004: 1 unverified: `82`
- exact_statistics-005: 1 unverified: `10`
- exact_statistics-006: 1 unverified: `19`
- exact_statistics-008: 4 unverified: `54`, `59`, `Q1 09:05`, `2`
- exact_statistics-010: 1 unverified: `146`
- single_game_narrative-001: 2 unverified: `18`, `18`
- single_game_narrative-003: 50 unverified: `9`, `3`, `6`, `12`, `27`, `25`, `30-36`, `-6`, `1`, `2`, `26`, `29-17` (+38 more)
- single_game_narrative-005: 35 unverified: `1`, `56.0-54.0`, `2`, `55.75-53.25`, `2`, `1 -0.25`, `-1`, `2`, `2`, `0`, `0`, `11-26` (+23 more)
- single_game_narrative-010: 2 unverified: `3-1`, `125`
- turning_points-001: 6 unverified: `17`, `33-36`, `50-36`, `07:29`, `03:49`, `12-0`
- turning_points-003: 4 unverified: `14`, `106-107`, `26`, `99-111`
- turning_points-005: 7 unverified: `73-73`, `Q3 03:58`, `48-27`, `Q2 00:08`, `Q3 10:47`, `42-54`, `50-54`
- turning_points-007: 3 unverified: `43`, `80-118`, `43`
- turning_points-008: 3 unverified: `21`, `21`, `21`
- turning_points-009: 1 unverified: `12`
