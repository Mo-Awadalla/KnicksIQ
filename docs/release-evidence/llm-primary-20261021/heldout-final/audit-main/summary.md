# Replacement factual audit: held-out v2 main 51f184a
Frozen code SHA: `51f184a23645f1d43f930a520a1cc053397a315b`.

Responses: 80. Numeric atoms found: 393. Checked: 242 (61.58% coverage). Verified: 209. Wrong: 33. Unverified: 151.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| heldout2-aliases_typos-001 |  | 12 | 12 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-aliases_typos-002 |  | 5 | 4 | 0 | 1 | 80% | UNVERIFIED | n/a |
| heldout2-aliases_typos-003 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-aliases_typos-004 |  | 3 | 1 | 0 | 2 | 33% | UNVERIFIED | n/a |
| heldout2-aliases_typos-005 |  | 7 | 6 | 0 | 1 | 86% | UNVERIFIED | n/a |
| heldout2-aliases_typos-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-aliases_typos-007 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-aliases_typos-008 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-aliases_typos-009 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| heldout2-aliases_typos-010 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-aliases_typos-011 |  | 3 | 2 | 1 | 0 | 100% | INCORRECT | n/a |
| heldout2-comparisons-001 |  | 5 | 1 | 0 | 4 | 20% | UNVERIFIED | n/a |
| heldout2-comparisons-002 |  | 10 | 5 | 0 | 5 | 50% | UNVERIFIED | n/a |
| heldout2-comparisons-003 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-comparisons-004 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-comparisons-005 |  | 3 | 0 | 2 | 1 | 67% | INCORRECT | n/a |
| heldout2-comparisons-006 |  | 5 | 1 | 0 | 4 | 20% | UNVERIFIED | n/a |
| heldout2-comparisons-007 |  | 5 | 1 | 0 | 4 | 20% | UNVERIFIED | n/a |
| heldout2-comparisons-008 |  | 4 | 0 | 3 | 1 | 75% | INCORRECT | n/a |
| heldout2-comparisons-009 |  | 3 | 1 | 0 | 2 | 33% | UNVERIFIED | n/a |
| heldout2-comparisons-010 |  | 8 | 7 | 0 | 1 | 88% | UNVERIFIED | n/a |
| heldout2-comparisons-011 |  | 2 | 0 | 2 | 0 | 100% | INCORRECT | n/a |
| heldout2-date_range_last_n-001 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-date_range_last_n-002 |  | 9 | 2 | 1 | 6 | 33% | INCORRECT | n/a |
| heldout2-date_range_last_n-003 |  | 4 | 1 | 3 | 0 | 100% | INCORRECT | n/a |
| heldout2-date_range_last_n-004 |  | 5 | 1 | 4 | 0 | 100% | INCORRECT | n/a |
| heldout2-date_range_last_n-005 |  | 2 | 0 | 2 | 0 | 100% | INCORRECT | n/a |
| heldout2-date_range_last_n-006 |  | 3 | 0 | 0 | 3 | 0% | UNVERIFIED | n/a |
| heldout2-date_range_last_n-007 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-date_range_last_n-008 |  | 2 | 0 | 1 | 1 | 50% | INCORRECT | n/a |
| heldout2-date_range_last_n-009 |  | 5 | 1 | 4 | 0 | 100% | INCORRECT | n/a |
| heldout2-date_range_last_n-010 |  | 4 | 0 | 4 | 0 | 100% | INCORRECT | n/a |
| heldout2-date_range_last_n-011 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-date_range_last_n-012 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-exact_statistics-001 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-exact_statistics-002 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-exact_statistics-003 |  | 4 | 2 | 1 | 1 | 75% | INCORRECT | n/a |
| heldout2-exact_statistics-004 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-exact_statistics-005 |  | 4 | 2 | 0 | 2 | 50% | UNVERIFIED | n/a |
| heldout2-exact_statistics-006 |  | 11 | 8 | 0 | 3 | 73% | UNVERIFIED | n/a |
| heldout2-exact_statistics-007 |  | 3 | 1 | 0 | 2 | 33% | UNVERIFIED | n/a |
| heldout2-exact_statistics-008 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-exact_statistics-009 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-exact_statistics-010 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-exact_statistics-011 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-exact_statistics-012 |  | 3 | 1 | 0 | 2 | 33% | UNVERIFIED | n/a |
| heldout2-single_game_narrative-001 |  | 9 | 5 | 1 | 3 | 67% | INCORRECT | n/a |
| heldout2-single_game_narrative-002 |  | 8 | 6 | 0 | 2 | 75% | UNVERIFIED | n/a |
| heldout2-single_game_narrative-003 |  | 8 | 6 | 0 | 2 | 75% | UNVERIFIED | n/a |
| heldout2-single_game_narrative-004 |  | 15 | 7 | 0 | 8 | 47% | UNVERIFIED | n/a |
| heldout2-single_game_narrative-005 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| heldout2-single_game_narrative-006 |  | 3 | 2 | 0 | 1 | 67% | UNVERIFIED | n/a |
| heldout2-single_game_narrative-007 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| heldout2-single_game_narrative-008 |  | 5 | 4 | 0 | 1 | 80% | UNVERIFIED | n/a |
| heldout2-single_game_narrative-009 |  | 5 | 2 | 0 | 3 | 40% | UNVERIFIED | n/a |
| heldout2-single_game_narrative-010 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-single_game_narrative-011 |  | 3 | 2 | 0 | 1 | 67% | UNVERIFIED | n/a |
| heldout2-turning_points-001 |  | 14 | 6 | 1 | 7 | 50% | INCORRECT | n/a |
| heldout2-turning_points-002 |  | 22 | 8 | 3 | 11 | 50% | INCORRECT | n/a |
| heldout2-turning_points-003 |  | 18 | 8 | 0 | 10 | 44% | UNVERIFIED | n/a |
| heldout2-turning_points-004 |  | 14 | 9 | 0 | 5 | 64% | UNVERIFIED | n/a |
| heldout2-turning_points-005 |  | 17 | 6 | 0 | 11 | 35% | UNVERIFIED | n/a |
| heldout2-turning_points-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-turning_points-007 |  | 14 | 6 | 0 | 8 | 43% | UNVERIFIED | n/a |
| heldout2-turning_points-008 |  | 5 | 3 | 0 | 2 | 60% | UNVERIFIED | n/a |
| heldout2-turning_points-009 |  | 10 | 3 | 0 | 7 | 30% | UNVERIFIED | n/a |
| heldout2-turning_points-010 |  | 17 | 6 | 0 | 11 | 35% | UNVERIFIED | n/a |
| heldout2-turning_points-011 |  | 14 | 6 | 0 | 8 | 43% | UNVERIFIED | n/a |
| heldout2-unsupported-001 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-unsupported-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-unsupported-003 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-unsupported-004 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-unsupported-005 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-unsupported-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-unsupported-007 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-unsupported-008 |  | 2 | 1 | 0 | 1 | 50% | UNVERIFIED | n/a |
| heldout2-unsupported-009 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-unsupported-010 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| heldout2-unsupported-011 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| heldout2-unsupported-012 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 11 | 38 | 32 | 1 | 5 | 87% |
| comparisons | 11 | 45 | 16 | 7 | 22 | 51% |
| date_range_last_n | 12 | 53 | 24 | 19 | 10 | 81% |
| exact_statistics | 12 | 40 | 29 | 1 | 10 | 75% |
| single_game_narrative | 11 | 67 | 43 | 1 | 23 | 66% |
| turning_points | 11 | 145 | 61 | 4 | 80 | 45% |
| unsupported | 12 | 5 | 4 | 0 | 1 | 80% |

## Wrong numbers (33)

### heldout2-exact_statistics-003 (trial n/a)

- `42` claimed; expected `82` (game count {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

### heldout2-date_range_last_n-002 (trial n/a)

- `113.4` claimed; expected `116.33663366336634` (points per game {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

### heldout2-date_range_last_n-003 (trial n/a)

- `12` claimed; expected `101` (game count {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

- `9` claimed; expected `69` (wins {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

- `3` claimed; expected `32` (losses {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

### heldout2-date_range_last_n-004 (trial n/a)

- `9-3` claimed; expected `69-32` (team record {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

- `12` claimed; expected `101` (game count {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

- `1,401` claimed; expected `11750` (team points {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

- `+168` claimed; expected `7.9405940594059405` (average margin {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

### heldout2-date_range_last_n-005 (trial n/a)

- `4-1` claimed; expected `32-20` (team record {'season_type': None, 'opp': None, 'loc': 'away', 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (away_team_id='NYK') order by game_date
  ```

- `4` claimed; expected `32` (wins {'season_type': None, 'opp': None, 'loc': 'away', 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (away_team_id='NYK') order by game_date
  ```

### heldout2-date_range_last_n-008 (trial n/a)

- `82` claimed; expected `11` (game count {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': 11, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date desc limit 11
  ```

### heldout2-date_range_last_n-009 (trial n/a)

- `2-3` claimed; expected `53-29` (team record {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `5` claimed; expected `82` (game count {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `11-3` claimed; expected `53-29` (team record {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `14` claimed; expected `82` (game count {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

### heldout2-date_range_last_n-010 (trial n/a)

- `9` claimed; expected `69` (wins {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

- `12` claimed; expected `101` (games {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

- `3` claimed; expected `32` (losses {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

- `12` claimed; expected `101` (games {'season_type': None, 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) order by game_date
  ```

### heldout2-comparisons-005 (trial n/a)

- `116.45` claimed; expected `115.0` (points per game {'season_type': 'regular', 'opp': 'BKN', 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (((home_team_id='NYK' and away_team_id='BKN') or (away_team_id='NYK' and home_team_id='BKN'))) order by game_date
  ```

- `6.33` claimed; expected `26.0` (average margin {'season_type': 'regular', 'opp': 'BKN', 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') and (((home_team_id='NYK' and away_team_id='BKN') or (away_team_id='NYK' and home_team_id='BKN'))) order by game_date
  ```

### heldout2-comparisons-008 (trial n/a)

- `-2.0` claimed; expected `6.329268292682927` (average margin {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `5` claimed; expected `82` (game count {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `5` claimed; expected `82` (game count {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

### heldout2-comparisons-011 (trial n/a)

- `567` claimed; expected `9549` (team points {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

- `5` claimed; expected `82` (games {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (season_type = 'regular') order by game_date
  ```

### heldout2-single_game_narrative-001 (trial n/a)

- `Q1 10:58` claimed; expected `Q1 07:55` (run end clock 2025-11-09).

  ```sql
  select ... game_events
  ```

### heldout2-turning_points-001 (trial n/a)

- `28-25` claimed; expected `None` (go-ahead).

  ```sql
  select ... game_events
  ```

### heldout2-turning_points-002 (trial n/a)

- `15-5` claimed; expected `no matching snapshot` (scoreboard at Q1 08:08).

  ```sql
  select ... game_events
  ```

- `14-0` claimed; expected `no matching run` (ORL run).

  ```sql
  select ... game_events
  ```

- `104-122` claimed; expected `no matching snapshot` (scoreboard at Q4 06:18).

  ```sql
  select ... game_events
  ```

### heldout2-aliases_typos-011 (trial n/a)

- `8` claimed; expected `108` (team points {'season_type': None, 'opp': 'HOU', 'loc': None, 'start': '2026-02-21', 'end': '2026-02-21', 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select id, game_date, season_type, home_team_id, away_team_id, home_score, away_score from games where ('NYK' in (home_team_id, away_team_id)) and (((home_team_id='NYK' and away_team_id='HOU') or (away_team_id='NYK' and home_team_id='HOU'))) and (game_date >= '2026-02-21') and (game_date <= '2026-02-21') order by game_date
  ```


## Unverified numbers (151)

- heldout2-aliases_typos-002: 1 unverified: `105.3`
- heldout2-aliases_typos-004: 2 unverified: `2.7`, `62`
- heldout2-aliases_typos-005: 1 unverified: `115-104`
- heldout2-aliases_typos-009: 1 unverified: `130-119`
- heldout2-comparisons-001: 4 unverified: `3.8`, `28`, `2.7`, `62`
- heldout2-comparisons-002: 5 unverified: `470`, `4`, `12`, `2`, `1`
- heldout2-comparisons-005: 1 unverified: `53-29`
- heldout2-comparisons-006: 4 unverified: `4.4`, `62`, `2.4`, `21`
- heldout2-comparisons-007: 4 unverified: `2.1`, `16`, `1.4`, `69`
- heldout2-comparisons-008: 1 unverified: `-10`
- heldout2-comparisons-009: 2 unverified: `6.3`, `13`
- heldout2-comparisons-010: 1 unverified: `121.75471698113208`
- heldout2-date_range_last_n-002: 6 unverified: `111`, `95`, `115`, `121`, `135`, `-2.0`
- heldout2-date_range_last_n-006: 3 unverified: `82`, `+6.33`, `9`
- heldout2-date_range_last_n-008: 1 unverified: `116.45121951219512`
- heldout2-exact_statistics-003: 1 unverified: `23-19`
- heldout2-exact_statistics-005: 2 unverified: `3.8`, `28`
- heldout2-exact_statistics-006: 3 unverified: `4`, `3`, `2`
- heldout2-exact_statistics-007: 2 unverified: `1.7`, `29`
- heldout2-exact_statistics-012: 2 unverified: `6.9`, `16`
- heldout2-single_game_narrative-001: 3 unverified: `0`, `Q4 09:42`, `118-79`
- heldout2-single_game_narrative-002: 2 unverified: `113-111`, `113-111`
- heldout2-single_game_narrative-003: 2 unverified: `146-112`, `146-112`
- heldout2-single_game_narrative-004: 8 unverified: `110-98`, `7:23`, `6`, `24-30`, `11`, `90-89`, `2:19`, `94-92`
- heldout2-single_game_narrative-005: 1 unverified: `5`
- heldout2-single_game_narrative-006: 1 unverified: `12`
- heldout2-single_game_narrative-007: 1 unverified: `123`
- heldout2-single_game_narrative-008: 1 unverified: `66`
- heldout2-single_game_narrative-009: 3 unverified: `69-63`, `61-55`, `13-10`
- heldout2-single_game_narrative-011: 1 unverified: `11`
- heldout2-turning_points-001: 7 unverified: `25-24`, `-1`, `+3`, `35-35`, `26-26`, `113-111`, `+3`
- heldout2-turning_points-002: 11 unverified: `27`, `Q3 00:32`, `93-96`, `10`, `Q1 08:08`, `15-5`, `15-19`, `Q1 07:34`, `04:39`, `18`, `Q4 06:18`
- heldout2-turning_points-003: 10 unverified: `38-28`, `+10`, `33-36`, `-3`, `38-28`, `+10`, `29-28`, `+1`, `32-28`, `+4`
- heldout2-turning_points-004: 5 unverified: `123-114`, `104-103`, `3`, `Q4 04:15`, `106-104`
- heldout2-turning_points-005: 11 unverified: `01-17`, `27-19`, `+8`, `29-36`, `-7`, `21-25`, `-4`, `22-26`, `-4`, `99-106`, `-7`
- heldout2-turning_points-007: 8 unverified: `38-22`, `+16`, `34-23`, `+11`, `30-26`, `+4`, `30-30`, `72-45`
- heldout2-turning_points-008: 2 unverified: `134-134`, `13-10`
- heldout2-turning_points-009: 7 unverified: `94-93`, `Q3 00:01`, `95-94`, `101-94`, `Q4 11:22`, `22`, `127-105`
- heldout2-turning_points-010: 11 unverified: `03-13`, `24-21`, `+3`, `32-24`, `+8`, `20-29`, `-9`, `25-18`, `+7`, `101-92`, `+9`
- heldout2-turning_points-011: 8 unverified: `31-15`, `+16`, `14-22`, `-8`, `30-28`, `+2`, `18-27`, `-9`
- heldout2-unsupported-008: 1 unverified: `1999`
