# Replacement factual audit: final-go trial 2

Responses: 70. Numeric atoms found: 673. Checked: 487 (72.36% coverage). Verified: 482. Wrong: 5. Unverified: 186.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-002 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-003 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-004 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-005 | 1 | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| aliases_typos-006 | 1 | 13 | 9 | 0 | 4 | 69% | UNVERIFIED | n/a |
| aliases_typos-007 | 1 | 16 | 10 | 0 | 6 | 62% | UNVERIFIED | n/a |
| aliases_typos-008 | 1 | 11 | 5 | 0 | 6 | 45% | UNVERIFIED | n/a |
| aliases_typos-009 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-010 | 1 | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| comparisons-001 | 1 | 10 | 10 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-002 | 1 | 5 | 1 | 1 | 3 | 40% | INCORRECT | n/a |
| comparisons-003 | 1 | 9 | 8 | 0 | 1 | 89% | UNVERIFIED | n/a |
| comparisons-004 | 1 | 17 | 5 | 0 | 12 | 29% | UNVERIFIED | n/a |
| comparisons-005 | 1 | 2 | 1 | 0 | 1 | 50% | UNVERIFIED | n/a |
| comparisons-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-007 | 1 | 5 | 4 | 0 | 1 | 80% | UNVERIFIED | n/a |
| comparisons-008 | 1 | 5 | 3 | 0 | 2 | 60% | UNVERIFIED | n/a |
| comparisons-009 | 1 | 22 | 6 | 0 | 16 | 27% | UNVERIFIED | n/a |
| comparisons-010 | 1 | 8 | 2 | 1 | 5 | 38% | INCORRECT | n/a |
| date_range_last_n-001 | 1 | 6 | 5 | 1 | 0 | 100% | INCORRECT | n/a |
| date_range_last_n-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-003 | 1 | 5 | 4 | 0 | 1 | 80% | UNVERIFIED | n/a |
| date_range_last_n-004 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| date_range_last_n-005 | 1 | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-006 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-007 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-008 | 1 | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-009 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-010 | 1 | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-001 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-002 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-003 | 1 | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-004 | 1 | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| exact_statistics-005 | 1 | 6 | 5 | 0 | 1 | 83% | UNVERIFIED | n/a |
| exact_statistics-006 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-007 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-008 | 1 | 3 | 2 | 0 | 1 | 67% | UNVERIFIED | n/a |
| exact_statistics-009 | 1 | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| exact_statistics-010 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-001 | 1 | 15 | 8 | 0 | 7 | 53% | UNVERIFIED | n/a |
| single_game_narrative-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-003 | 1 | 78 | 20 | 0 | 58 | 26% | UNVERIFIED | n/a |
| single_game_narrative-004 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-005 | 1 | 37 | 2 | 0 | 35 | 5% | UNVERIFIED | n/a |
| single_game_narrative-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-007 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-008 | 1 | 28 | 28 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-009 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-010 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-001 | 1 | 8 | 2 | 1 | 5 | 38% | INCORRECT | n/a |
| turning_points-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-003 | 1 | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| turning_points-004 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-005 | 1 | 13 | 6 | 0 | 7 | 46% | UNVERIFIED | n/a |
| turning_points-006 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-007 | 1 | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| turning_points-008 | 1 | 27 | 25 | 0 | 2 | 93% | UNVERIFIED | n/a |
| turning_points-009 | 1 | 20 | 17 | 1 | 2 | 90% | INCORRECT | n/a |
| turning_points-010 | 1 | 8 | 8 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-001 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-002 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-003 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-004 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-005 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-006 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-007 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-008 | 1 | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-009 | 1 | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-010 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 10 | 144 | 124 | 0 | 20 | 86% |
| comparisons | 10 | 83 | 40 | 2 | 41 | 51% |
| date_range_last_n | 10 | 43 | 41 | 1 | 1 | 98% |
| exact_statistics | 10 | 43 | 39 | 0 | 4 | 91% |
| single_game_narrative | 10 | 172 | 72 | 0 | 100 | 42% |
| turning_points | 10 | 175 | 153 | 2 | 20 | 89% |
| unsupported | 10 | 13 | 13 | 0 | 0 | 100% |

## Wrong numbers (5)

### date_range_last_n-001 (trial 1)

- `+12` claimed; expected `2.4` (margin per game {'season_type': 'playoffs', 'opp': None, 'loc': None, 'start': '2026-06-03', 'end': '2026-06-13', 'last_n': 5, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'playoffs') and (game_date >= '2026-06-03') and (game_date <= '2026-06-13') order by game_date desc limit 5
  ```

### comparisons-002 (trial 1)

- `74` claimed; expected `75` (Karl-Anthony Towns appearances {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select g.game_date, g.id, s.points, s.rebounds, s.assists, s.turnovers from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name='Karl-Anthony Towns' and s.minutes > 0 and g.season_type='regular' order by g.game_date
  ```

### comparisons-010 (trial 1)

- `29` claimed; expected `53` (game count {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': 'W'}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and ((home_team_id='NYK' and home_score>away_score) or (away_team_id='NYK' and away_score>home_score)) order by game_date
  ```

### turning_points-001 (trial 1)

- `17-0` claimed; expected `no matching run` (BOS run).

  ```sql
  select ... game_events
  ```

### turning_points-009 (trial 1)

- `69-68` claimed; expected `None` (first tie).

  ```sql
  select ... game_events
  ```


## Unverified numbers (186)

- aliases_typos-005: 2 unverified: `43`, `43`
- aliases_typos-006: 4 unverified: `+11.00`, `2-1`, `2.00`, `4-2`
- aliases_typos-007: 6 unverified: `34-35`, `23-27`, `22-21`, `28-24`, `+4`, `-4`
- aliases_typos-008: 6 unverified: `5`, `16.6`, `15`, `30`, `11`, `13`
- aliases_typos-010: 2 unverified: `43`, `43`
- comparisons-002: 3 unverified: `26.0`, `20.1`, `75`
- comparisons-003: 1 unverified: `3-1`
- comparisons-004: 12 unverified: `7-3`, `121.8`, `112.7`, `6-4`, `111.2`, `108.3`, `121.8`, `111.2`, `+9.1`, `+2.9`, `112.7`, `108.3`
- comparisons-005: 1 unverified: `0-29`
- comparisons-007: 1 unverified: `3-1`
- comparisons-008: 2 unverified: `11.9`, `7.4`
- comparisons-009: 16 unverified: `2375`, `28.96`, `2307`, `28.13`, `+68`, `37-5`, `-40`, `2316`, `28.24`, `2078`, `25.34`, `+238` (+4 more)
- comparisons-010: 5 unverified: `105.51`, `+16.25`, `106.76`, `118.55`, `-11.79`
- date_range_last_n-003: 1 unverified: `5`
- exact_statistics-004: 1 unverified: `6.3`
- exact_statistics-005: 1 unverified: `+401`
- exact_statistics-008: 1 unverified: `54`
- exact_statistics-009: 1 unverified: `80-118`
- single_game_narrative-001: 7 unverified: `14`, `37-23`, `11:07`, `Q2 3:26`, `50-49`, `94-76`, `0:03`
- single_game_narrative-003: 58 unverified: `12`, `27`, `25`, `30-36`, `-6`, `128-125`, `1`, `2`, `26`, `29-17`, `+12`, `99-111` (+46 more)
- single_game_narrative-005: 35 unverified: `1`, `56.0-54.0`, `2`, `55.75-53.25`, `2`, `1 -0.25`, `-1`, `2`, `2`, `0`, `0`, `11-26` (+23 more)
- turning_points-001: 5 unverified: `Q2 07:29`, `Q2 03:49`, `33-36`, `50-36`, `12-0`
- turning_points-003: 2 unverified: `26`, `26`
- turning_points-005: 7 unverified: `21`, `25-46`, `Q2 09:30`, `73-73`, `Q3 03:58`, `48-27`, `110-107`
- turning_points-007: 2 unverified: `43`, `43`
- turning_points-008: 2 unverified: `21`, `129-101`
- turning_points-009: 2 unverified: `Q3 03:54`, `24`
