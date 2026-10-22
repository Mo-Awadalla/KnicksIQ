# Replacement factual audit: w4-bench trial 2

Responses: 70. Numeric atoms found: 644. Checked: 477 (74.07% coverage). Verified: 477. Wrong: 0. Unverified: 167.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-002 | 1 | 12 | 9 | 0 | 3 | 75% | UNVERIFIED | n/a |
| aliases_typos-003 | 1 | 15 | 7 | 0 | 8 | 47% | UNVERIFIED | n/a |
| aliases_typos-004 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-005 | 1 | 7 | 7 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-006 | 1 | 16 | 14 | 0 | 2 | 88% | UNVERIFIED | n/a |
| aliases_typos-007 | 1 | 23 | 4 | 0 | 19 | 17% | UNVERIFIED | n/a |
| aliases_typos-008 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-009 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-010 | 1 | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| comparisons-001 | 1 | 10 | 10 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-002 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-003 | 1 | 9 | 7 | 0 | 2 | 78% | UNVERIFIED | n/a |
| comparisons-004 | 1 | 13 | 8 | 0 | 5 | 62% | UNVERIFIED | n/a |
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
| date_range_last_n-005 | 1 | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-006 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-007 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-008 | 1 | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-009 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-010 | 1 | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-001 | 1 | 5 | 4 | 0 | 1 | 80% | UNVERIFIED | n/a |
| exact_statistics-002 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-003 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-004 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-005 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-006 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-007 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-008 | 1 | 8 | 5 | 0 | 3 | 62% | UNVERIFIED | n/a |
| exact_statistics-009 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-010 | 1 | 3 | 2 | 0 | 1 | 67% | UNVERIFIED | n/a |
| single_game_narrative-001 | 1 | 44 | 42 | 0 | 2 | 95% | UNVERIFIED | n/a |
| single_game_narrative-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-003 | 1 | 71 | 24 | 0 | 47 | 34% | UNVERIFIED | n/a |
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
| turning_points-005 | 1 | 13 | 10 | 0 | 3 | 77% | UNVERIFIED | n/a |
| turning_points-006 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-007 | 1 | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
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
| unsupported-008 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-009 | 1 | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-010 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 10 | 130 | 96 | 0 | 34 | 74% |
| comparisons | 10 | 62 | 39 | 0 | 23 | 63% |
| date_range_last_n | 10 | 40 | 40 | 0 | 0 | 100% |
| exact_statistics | 10 | 42 | 37 | 0 | 5 | 88% |
| single_game_narrative | 10 | 207 | 121 | 0 | 86 | 58% |
| turning_points | 10 | 156 | 137 | 0 | 19 | 88% |
| unsupported | 10 | 7 | 7 | 0 | 0 | 100% |

## Wrong numbers (0)

None.

## Unverified numbers (167)

- aliases_typos-002: 3 unverified: `117-123`, `111-89`, `112-106`
- aliases_typos-003: 8 unverified: `42`, `8`, `9`, `5`, `40`, `5`, `8`, `1`
- aliases_typos-006: 2 unverified: `-2.00`, `+17.50`
- aliases_typos-007: 19 unverified: `4`, `10`, `31`, `34-35`, `-1`, `11`, `2`, `23-27`, `-4`, `2`, `22`, `22-21` (+7 more)
- aliases_typos-010: 2 unverified: `43`, `43`
- comparisons-003: 2 unverified: `+8.00`, `+19.60`
- comparisons-004: 5 unverified: `7-3`, `6-4`, `111.2`, `+9.1`, `+2.9`
- comparisons-009: 16 unverified: `2375`, `28.96`, `2307`, `28.13`, `+68`, `37-5`, `-40`, `2316`, `28.24`, `2078`, `25.34`, `+238` (+4 more)
- exact_statistics-001: 1 unverified: `+519`
- exact_statistics-008: 3 unverified: `59`, `Q1 09:05`, `2`
- exact_statistics-010: 1 unverified: `146`
- single_game_narrative-001: 2 unverified: `18`, `18`
- single_game_narrative-003: 47 unverified: `12`, `27`, `25`, `30-36`, `-6`, `1`, `2`, `26`, `29-17`, `+12`, `4`, `6` (+35 more)
- single_game_narrative-005: 35 unverified: `1`, `56.0-54.0`, `2`, `55.75-53.25`, `2`, `1 -0.25`, `-1`, `2`, `2`, `0`, `0`, `11-26` (+23 more)
- single_game_narrative-010: 2 unverified: `3-1`, `125`
- turning_points-001: 6 unverified: `17`, `33-36`, `50-36`, `07:29`, `03:49`, `12-0`
- turning_points-003: 4 unverified: `14`, `106-107`, `26`, `99-111`
- turning_points-005: 3 unverified: `73-73`, `Q3 03:58`, `48-27`
- turning_points-007: 2 unverified: `43`, `43`
- turning_points-008: 3 unverified: `21`, `21`, `21`
- turning_points-009: 1 unverified: `12`
