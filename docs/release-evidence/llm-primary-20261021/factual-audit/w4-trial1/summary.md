# Replacement factual audit: w4-bench trial 1

Responses: 70. Numeric atoms found: 597. Checked: 384 (64.32% coverage). Verified: 384. Wrong: 0. Unverified: 213.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-002 |  | 11 | 11 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-003 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-004 |  | 9 | 3 | 0 | 6 | 33% | UNVERIFIED | n/a |
| aliases_typos-005 |  | 8 | 8 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-006 |  | 13 | 10 | 0 | 3 | 77% | UNVERIFIED | n/a |
| aliases_typos-007 |  | 62 | 18 | 0 | 44 | 29% | UNVERIFIED | n/a |
| aliases_typos-008 |  | 10 | 1 | 0 | 9 | 10% | UNVERIFIED | n/a |
| aliases_typos-009 |  | 18 | 5 | 0 | 13 | 28% | UNVERIFIED | n/a |
| aliases_typos-010 |  | 10 | 8 | 0 | 2 | 80% | UNVERIFIED | n/a |
| comparisons-001 |  | 10 | 10 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-003 |  | 9 | 4 | 0 | 5 | 44% | UNVERIFIED | n/a |
| comparisons-004 |  | 11 | 11 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-005 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-007 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-008 |  | 5 | 1 | 0 | 4 | 20% | UNVERIFIED | n/a |
| comparisons-009 |  | 22 | 6 | 0 | 16 | 27% | UNVERIFIED | n/a |
| comparisons-010 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| date_range_last_n-001 |  | 10 | 6 | 0 | 4 | 60% | UNVERIFIED | n/a |
| date_range_last_n-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-003 |  | 9 | 2 | 0 | 7 | 22% | UNVERIFIED | n/a |
| date_range_last_n-004 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-005 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-006 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-007 |  | 6 | 5 | 0 | 1 | 83% | UNVERIFIED | n/a |
| date_range_last_n-008 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-009 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-010 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-001 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-002 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-003 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| exact_statistics-004 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-005 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-006 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| exact_statistics-007 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| exact_statistics-008 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-009 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-010 |  | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| single_game_narrative-001 |  | 15 | 14 | 0 | 1 | 93% | UNVERIFIED | n/a |
| single_game_narrative-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-003 |  | 58 | 13 | 0 | 45 | 22% | UNVERIFIED | n/a |
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
| turning_points-005 |  | 13 | 10 | 0 | 3 | 77% | UNVERIFIED | n/a |
| turning_points-006 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-007 |  | 9 | 9 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-008 |  | 18 | 16 | 0 | 2 | 89% | UNVERIFIED | n/a |
| turning_points-009 |  | 13 | 11 | 0 | 2 | 85% | UNVERIFIED | n/a |
| turning_points-010 |  | 8 | 8 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-001 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-002 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-003 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-004 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-005 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-006 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-007 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-008 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-009 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-010 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 10 | 149 | 72 | 0 | 77 | 48% |
| comparisons | 10 | 61 | 36 | 0 | 25 | 59% |
| date_range_last_n | 10 | 55 | 43 | 0 | 12 | 78% |
| exact_statistics | 10 | 43 | 39 | 0 | 4 | 91% |
| single_game_narrative | 10 | 158 | 77 | 0 | 81 | 49% |
| turning_points | 10 | 121 | 107 | 0 | 14 | 88% |
| unsupported | 10 | 10 | 10 | 0 | 0 | 100% |

## Wrong numbers (0)

None.

## Unverified numbers (213)

- aliases_typos-004: 6 unverified: `17.4`, `5`, `8`, `22`, `22`, `16`
- aliases_typos-006: 3 unverified: `+11.00`, `-2.00`, `+17.50`
- aliases_typos-007: 44 unverified: `10-31`, `27-35`, `-8`, `26-37`, `-11`, `38-28`, `+10`, `34-35`, `-1`, `125-135`, `-10`, `11-02` (+32 more)
- aliases_typos-008: 9 unverified: `5`, `16.6`, `+17`, `+19`, `+19`, `+11`, `+13`, `3–4`, `30`
- aliases_typos-009: 13 unverified: `10`, `2`, `1`, `2`, `+10`, `105-95`, `13`, `4`, `1`, `2`, `3`, `+3` (+1 more)
- aliases_typos-010: 2 unverified: `71-52`, `Q2 3:51`
- comparisons-003: 5 unverified: `115.0`, `3-1`, `+8.0`, `111.25`, `4-5`
- comparisons-008: 4 unverified: `11.9`, `75`, `7.4`, `66`
- comparisons-009: 16 unverified: `2375`, `28.96`, `2307`, `28.13`, `+68`, `37-5`, `-40`, `2316`, `28.24`, `2078`, `25.34`, `+238` (+4 more)
- date_range_last_n-001: 4 unverified: `105-95`, `105-104`, `107-106`, `94-90`
- date_range_last_n-003: 7 unverified: `5`, `32.6`, `30`, `20`, `32`, `36`, `45`
- date_range_last_n-007: 1 unverified: `+9.75`
- exact_statistics-003: 1 unverified: `+6.3`
- exact_statistics-006: 1 unverified: `23-19`
- exact_statistics-007: 1 unverified: `53-29`
- exact_statistics-010: 1 unverified: `146`
- single_game_narrative-001: 1 unverified: `18`
- single_game_narrative-003: 45 unverified: `12-27`, `30-36`, `-6`, `128-125`, `+3`, `01-02`, `29-17`, `+12`, `99-111`, `-12`, `04-06`, `27-26` (+33 more)
- single_game_narrative-005: 35 unverified: `1`, `56.0-54.0`, `2`, `55.75-53.25`, `2`, `1 -0.25`, `-1`, `2`, `2`, `0`, `0`, `11-26` (+23 more)
- turning_points-001: 5 unverified: `Q2 07:29`, `Q2 03:49`, `33-36`, `50-36`, `12-0`
- turning_points-003: 2 unverified: `26`, `26`
- turning_points-005: 3 unverified: `Q3 03:58`, `73-73`, `48-27`
- turning_points-008: 2 unverified: `21`, `6`
- turning_points-009: 2 unverified: `Q2 09:15`, `22-34`
