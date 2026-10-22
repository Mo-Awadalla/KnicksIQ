# Replacement factual audit: w4-bench trial 1

Responses: 70. Numeric atoms found: 597. Checked: 341 (57.12% coverage). Verified: 320. Wrong: 21. Unverified: 256.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 |  | 5 | 4 | 0 | 1 | 80% | UNVERIFIED | n/a |
| aliases_typos-002 |  | 11 | 8 | 0 | 3 | 73% | UNVERIFIED | n/a |
| aliases_typos-003 |  | 3 | 1 | 2 | 0 | 100% | INCORRECT | n/a |
| aliases_typos-004 |  | 9 | 3 | 0 | 6 | 33% | UNVERIFIED | n/a |
| aliases_typos-005 |  | 8 | 8 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-006 |  | 13 | 7 | 0 | 6 | 54% | UNVERIFIED | n/a |
| aliases_typos-007 |  | 62 | 18 | 0 | 44 | 29% | UNVERIFIED | n/a |
| aliases_typos-008 |  | 10 | 1 | 0 | 9 | 10% | UNVERIFIED | n/a |
| aliases_typos-009 |  | 18 | 5 | 0 | 13 | 28% | UNVERIFIED | n/a |
| aliases_typos-010 |  | 10 | 6 | 0 | 4 | 60% | UNVERIFIED | n/a |
| comparisons-001 |  | 10 | 4 | 4 | 2 | 80% | INCORRECT | n/a |
| comparisons-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-003 |  | 9 | 2 | 0 | 7 | 22% | UNVERIFIED | n/a |
| comparisons-004 |  | 11 | 3 | 2 | 6 | 45% | INCORRECT | n/a |
| comparisons-005 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-007 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-008 |  | 5 | 1 | 0 | 4 | 20% | UNVERIFIED | n/a |
| comparisons-009 |  | 22 | 6 | 0 | 16 | 27% | UNVERIFIED | n/a |
| comparisons-010 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| date_range_last_n-001 |  | 10 | 6 | 0 | 4 | 60% | UNVERIFIED | n/a |
| date_range_last_n-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-003 |  | 9 | 2 | 0 | 7 | 22% | UNVERIFIED | n/a |
| date_range_last_n-004 |  | 6 | 3 | 1 | 2 | 67% | INCORRECT | n/a |
| date_range_last_n-005 |  | 5 | 0 | 4 | 1 | 80% | INCORRECT | n/a |
| date_range_last_n-006 |  | 2 | 1 | 0 | 1 | 50% | UNVERIFIED | n/a |
| date_range_last_n-007 |  | 6 | 4 | 0 | 2 | 67% | UNVERIFIED | n/a |
| date_range_last_n-008 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-009 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-010 |  | 6 | 5 | 0 | 1 | 83% | UNVERIFIED | n/a |
| exact_statistics-001 |  | 5 | 4 | 0 | 1 | 80% | UNVERIFIED | n/a |
| exact_statistics-002 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-003 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| exact_statistics-004 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-005 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| exact_statistics-006 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| exact_statistics-007 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| exact_statistics-008 |  | 6 | 4 | 1 | 1 | 83% | INCORRECT | n/a |
| exact_statistics-009 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-010 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| single_game_narrative-001 |  | 15 | 14 | 0 | 1 | 93% | UNVERIFIED | n/a |
| single_game_narrative-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-003 |  | 58 | 9 | 2 | 47 | 19% | INCORRECT | n/a |
| single_game_narrative-004 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-005 |  | 37 | 2 | 0 | 35 | 5% | UNVERIFIED | n/a |
| single_game_narrative-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-007 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-008 |  | 28 | 28 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-009 |  | 8 | 8 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-010 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-001 |  | 8 | 3 | 0 | 5 | 38% | UNVERIFIED | n/a |
| turning_points-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-003 |  | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| turning_points-004 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| turning_points-005 |  | 13 | 4 | 1 | 8 | 38% | INCORRECT | n/a |
| turning_points-006 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-007 |  | 9 | 9 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-008 |  | 18 | 12 | 1 | 5 | 72% | INCORRECT | n/a |
| turning_points-009 |  | 13 | 5 | 1 | 7 | 46% | INCORRECT | n/a |
| turning_points-010 |  | 8 | 8 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-001 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-002 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-003 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-004 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-005 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-006 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-007 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-008 |  | 3 | 1 | 2 | 0 | 100% | INCORRECT | n/a |
| unsupported-009 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-010 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 10 | 149 | 61 | 2 | 86 | 42% |
| comparisons | 10 | 61 | 20 | 6 | 35 | 43% |
| date_range_last_n | 10 | 55 | 32 | 5 | 18 | 67% |
| exact_statistics | 10 | 43 | 35 | 1 | 7 | 84% |
| single_game_narrative | 10 | 158 | 73 | 2 | 83 | 47% |
| turning_points | 10 | 121 | 91 | 3 | 27 | 78% |
| unsupported | 10 | 10 | 8 | 2 | 0 | 100% |

## Wrong numbers (21)

### exact_statistics-008 (trial n/a)

- `59` claimed; expected `None` (lost lead).

  ```sql
  select ... game_events
  ```

### date_range_last_n-004 (trial n/a)

- `Jan 1–31` claimed; expected `2026-01-02..2026-01-30` (archived date window).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (game_date >= '2026-01-01') and (game_date <= '2026-01-31') order by game_date
  ```

### date_range_last_n-005 (trial n/a)

- `27` claimed; expected `82` (game count {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `113.26` claimed; expected `116.45121951219512` (points for/against per game).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `106.59` claimed; expected `110.1219512195122` (points for/against per game).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `+6.67` claimed; expected `6.329268292682927` (average margin {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

### comparisons-001 (trial n/a)

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

### comparisons-004 (trial n/a)

- `-9.1` claimed; expected `9.1` (average margin {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': 10, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date asc limit 10
  ```

- `-2.9` claimed; expected `2.9` (average margin {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': 10, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date desc limit 10
  ```

### single_game_narrative-003 (trial n/a)

- `9` claimed; expected `6` (games with period scores {'season_type': 'playoffs', 'opp': 'ATL', 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select p.period, sum(p.points) filter (where p.team_id='NYK') nyk, sum(p.points) filter (where p.team_id<>'NYK') opp, count(distinct p.game_id) games from period_scores p join games g on g.id=p.game_id where 'NYK' in (g.home_team_id,g.away_team_id) and p.period=3
  ```

- `9` claimed; expected `6` (game count {'season_type': 'playoffs', 'opp': 'ATL', 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'playoffs') and (((home_team_id='NYK' and away_team_id='ATL') or (away_team_id='NYK' and home_team_id='ATL'))) order by game_date
  ```

### turning_points-005 (trial n/a)

- `8-0` claimed; expected `no matching run` (GSW run).

  ```sql
  select ... game_events
  ```

### turning_points-008 (trial n/a)

- `83-104` claimed; expected `no matching snapshot` (scoreboard at Q4 08:32).

  ```sql
  select ... game_events
  ```

### turning_points-009 (trial n/a)

- `7-0` claimed; expected `no matching run` (TOR run).

  ```sql
  select ... game_events
  ```

### aliases_typos-003 (trial n/a)

- `26.0` claimed; expected `26.516129032258064` (Jalen Brunson points per appearance {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select g.game_date, g.id, s.points, s.rebounds, s.assists, s.turnovers from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 order by g.game_date
  ```

- `74` claimed; expected `93` (Jalen Brunson points per appearance {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select g.game_date, g.id, s.points, s.rebounds, s.assists, s.turnovers from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 order by g.game_date
  ```

### unsupported-008 (trial n/a)

- `26.0` claimed; expected `26.516129032258064` (Jalen Brunson points per appearance {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select g.game_date, g.id, s.points, s.rebounds, s.assists, s.turnovers from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 order by g.game_date
  ```

- `74` claimed; expected `93` (Jalen Brunson points per appearance {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select g.game_date, g.id, s.points, s.rebounds, s.assists, s.turnovers from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name='Jalen Brunson' and s.minutes > 0 order by g.game_date
  ```


## Unverified numbers (256)

- aliases_typos-001: 1 unverified: `103.25`
- aliases_typos-002: 3 unverified: `117-123`, `111-89`, `112-106`
- aliases_typos-004: 6 unverified: `17.4`, `5`, `8`, `22`, `22`, `16`
- aliases_typos-006: 6 unverified: `104.78`, `+11.00`, `2-1`, `-2.00`, `4-2`, `+17.50`
- aliases_typos-007: 44 unverified: `10-31`, `27-35`, `-8`, `26-37`, `-11`, `38-28`, `+10`, `34-35`, `-1`, `125-135`, `-10`, `11-02` (+32 more)
- aliases_typos-008: 9 unverified: `5`, `16.6`, `+17`, `+19`, `+19`, `+11`, `+13`, `3–4`, `30`
- aliases_typos-009: 13 unverified: `10`, `2`, `1`, `2`, `+10`, `105-95`, `13`, `4`, `1`, `2`, `3`, `+3` (+1 more)
- aliases_typos-010: 4 unverified: `71-52`, `Q2 3:51`, `43`, `80-118`
- comparisons-001: 2 unverified: `30-10`, `23-19`
- comparisons-003: 7 unverified: `115.0`, `95.4`, `3-1`, `+8.0`, `111.25`, `103.25`, `4-5`
- comparisons-004: 6 unverified: `7-3`, `121.8`, `112.7`, `6-4`, `111.2`, `108.3`
- comparisons-008: 4 unverified: `11.9`, `75`, `7.4`, `66`
- comparisons-009: 16 unverified: `2375`, `28.96`, `2307`, `28.13`, `+68`, `37-5`, `-40`, `2316`, `28.24`, `2078`, `25.34`, `+238` (+4 more)
- date_range_last_n-001: 4 unverified: `105-95`, `105-104`, `107-106`, `94-90`
- date_range_last_n-003: 7 unverified: `5`, `32.6`, `30`, `20`, `32`, `36`, `45`
- date_range_last_n-004: 2 unverified: `15`, `+44`
- date_range_last_n-005: 1 unverified: `18-9`
- date_range_last_n-006: 1 unverified: `8`
- date_range_last_n-007: 2 unverified: `8`, `+9.75`
- date_range_last_n-010: 1 unverified: `112.7`
- exact_statistics-001: 1 unverified: `-519`
- exact_statistics-003: 1 unverified: `+6.3`
- exact_statistics-005: 1 unverified: `10`
- exact_statistics-006: 1 unverified: `23-19`
- exact_statistics-007: 1 unverified: `53-29`
- exact_statistics-008: 1 unverified: `54`
- exact_statistics-010: 1 unverified: `146`
- single_game_narrative-001: 1 unverified: `18`
- single_game_narrative-003: 47 unverified: `3`, `6`, `12-27`, `30-36`, `-6`, `128-125`, `+3`, `01-02`, `29-17`, `+12`, `99-111`, `-12` (+35 more)
- single_game_narrative-005: 35 unverified: `1`, `56.0-54.0`, `2`, `55.75-53.25`, `2`, `1 -0.25`, `-1`, `2`, `2`, `0`, `0`, `11-26` (+23 more)
- turning_points-001: 5 unverified: `Q2 07:29`, `Q2 03:49`, `33-36`, `50-36`, `12-0`
- turning_points-003: 2 unverified: `26`, `26`
- turning_points-005: 8 unverified: `21`, `Q3 03:58`, `73-73`, `48-27`, `Q2 00:08`, `Q3 10:47`, `42-54`, `50-54`
- turning_points-008: 5 unverified: `96-110`, `21`, `Q4 08:32`, `129-101`, `6`
- turning_points-009: 7 unverified: `12`, `Q2 09:15`, `22-34`, `Q3 07:46`, `Q3 06:36`, `55-66`, `62-66`
