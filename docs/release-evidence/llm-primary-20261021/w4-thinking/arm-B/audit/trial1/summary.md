# Replacement factual audit: arm B trial 1

Responses: 30. Numeric atoms found: 253. Checked: 168 (66.40% coverage). Verified: 168. Wrong: 0. Unverified: 85.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-002 |  | 16 | 15 | 0 | 1 | 94% | UNVERIFIED | n/a |
| aliases_typos-003 |  | 35 | 7 | 0 | 28 | 20% | UNVERIFIED | n/a |
| comparisons-001 |  | 10 | 10 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-003 |  | 9 | 7 | 0 | 2 | 78% | UNVERIFIED | n/a |
| comparisons-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-007 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-010 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| date_range_last_n-001 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-003 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-005 |  | 6 | 5 | 0 | 1 | 83% | UNVERIFIED | n/a |
| date_range_last_n-008 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-001 |  | 5 | 4 | 0 | 1 | 80% | UNVERIFIED | n/a |
| exact_statistics-002 |  | 3 | 2 | 0 | 1 | 67% | UNVERIFIED | n/a |
| exact_statistics-003 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-001 |  | 10 | 8 | 0 | 2 | 80% | UNVERIFIED | n/a |
| single_game_narrative-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-003 |  | 58 | 13 | 0 | 45 | 22% | UNVERIFIED | n/a |
| single_game_narrative-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-009 |  | 8 | 8 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-001 |  | 44 | 42 | 0 | 2 | 95% | UNVERIFIED | n/a |
| turning_points-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| turning_points-003 |  | 16 | 14 | 0 | 2 | 88% | UNVERIFIED | n/a |
| unsupported-001 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-003 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-004 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 3 | 57 | 28 | 0 | 29 | 49% |
| comparisons | 6 | 23 | 21 | 0 | 2 | 91% |
| date_range_last_n | 5 | 22 | 21 | 0 | 1 | 95% |
| exact_statistics | 3 | 13 | 11 | 0 | 2 | 85% |
| single_game_narrative | 5 | 76 | 29 | 0 | 47 | 38% |
| turning_points | 3 | 60 | 56 | 0 | 4 | 93% |
| unsupported | 5 | 2 | 2 | 0 | 0 | 100% |

## Wrong numbers (0)

None.

## Unverified numbers (85)

- aliases_typos-002: 1 unverified: `+32`
- aliases_typos-003: 28 unverified: `47`, `3`, `8`, `0`, `42`, `8`, `9`, `5`, `40`, `5`, `8`, `1` (+16 more)
- comparisons-003: 2 unverified: `115.00`, `95.40`
- date_range_last_n-005: 1 unverified: `106.59`
- exact_statistics-001: 1 unverified: `519`
- exact_statistics-002: 1 unverified: `9,549`
- single_game_narrative-001: 2 unverified: `37-23`, `3:26`
- single_game_narrative-003: 45 unverified: `12-27`, `30-36`, `-6`, `128-125`, `+3`, `01-02`, `29-17`, `+12`, `99-111`, `-12`, `04-06`, `27-26` (+33 more)
- turning_points-001: 2 unverified: `18`, `18`
- turning_points-003: 2 unverified: `26`, `99-111`
