# Replacement factual audit: arm A trial 2

Responses: 30. Numeric atoms found: 264. Checked: 220 (83.33% coverage). Verified: 219. Wrong: 1. Unverified: 44.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 | 1 | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-002 | 1 | 16 | 16 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-003 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-001 | 1 | 10 | 10 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-002 | 1 | 5 | 1 | 1 | 3 | 40% | INCORRECT | n/a |
| comparisons-003 | 1 | 20 | 20 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-007 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-010 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| date_range_last_n-001 | 1 | 6 | 5 | 0 | 1 | 83% | UNVERIFIED | n/a |
| date_range_last_n-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-003 | 1 | 8 | 1 | 0 | 7 | 12% | UNVERIFIED | n/a |
| date_range_last_n-005 | 1 | 6 | 4 | 0 | 2 | 67% | UNVERIFIED | n/a |
| date_range_last_n-008 | 1 | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-001 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-002 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-003 | 1 | 5 | 3 | 0 | 2 | 60% | UNVERIFIED | n/a |
| single_game_narrative-001 | 1 | 44 | 42 | 0 | 2 | 95% | UNVERIFIED | n/a |
| single_game_narrative-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-003 | 1 | 56 | 31 | 0 | 25 | 55% | UNVERIFIED | n/a |
| single_game_narrative-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-009 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| turning_points-001 | 1 | 7 | 7 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-003 | 1 | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| unsupported-001 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-002 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-003 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-004 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 3 | 25 | 25 | 0 | 0 | 100% |
| comparisons | 6 | 39 | 35 | 1 | 3 | 92% |
| date_range_last_n | 5 | 27 | 17 | 0 | 10 | 63% |
| exact_statistics | 3 | 13 | 11 | 0 | 2 | 85% |
| single_game_narrative | 5 | 105 | 78 | 0 | 27 | 74% |
| turning_points | 3 | 55 | 53 | 0 | 2 | 96% |
| unsupported | 5 | 0 | 0 | 0 | 0 | n/a |

## Wrong numbers (1)

### comparisons-002 (trial 1)

- `74` claimed; expected `75` (Karl-Anthony Towns appearances {'season_type': 'regular', 'opp': None, 'loc': None, 'start': None, 'end': None, 'last_n': None, 'first_n': None, 'result': None}).

  ```sql
  select g.game_date, g.id, s.points, s.rebounds, s.assists, s.turnovers from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name='Karl-Anthony Towns' and s.minutes > 0 and g.season_type='regular' order by g.game_date
  ```


## Unverified numbers (44)

- comparisons-002: 3 unverified: `26.0`, `20.1`, `75`
- date_range_last_n-001: 1 unverified: `+12`
- date_range_last_n-003: 7 unverified: `5`, `32.6`, `30`, `20`, `32`, `36`, `45`
- date_range_last_n-005: 2 unverified: `113.26`, `106.59`
- exact_statistics-003: 2 unverified: `+6.33`, `53-29`
- single_game_narrative-001: 2 unverified: `18`, `18`
- single_game_narrative-003: 25 unverified: `30-36`, `-6`, `128-125`, `29-17`, `+12`, `99-111`, `27-26`, `+1`, `108-105`, `30-28`, `+2`, `15-28` (+13 more)
- turning_points-003: 2 unverified: `26`, `26`
