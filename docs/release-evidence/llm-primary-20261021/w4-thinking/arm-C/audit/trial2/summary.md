# Replacement factual audit: arm C trial 2

Responses: 30. Numeric atoms found: 276. Checked: 221 (80.07% coverage). Verified: 221. Wrong: 0. Unverified: 55.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-002 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| aliases_typos-003 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-001 | 1 | 10 | 10 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-002 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-003 | 1 | 20 | 20 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-007 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-010 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| date_range_last_n-001 | 1 | 4 | 3 | 0 | 1 | 75% | UNVERIFIED | n/a |
| date_range_last_n-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-003 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-005 | 1 | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-008 | 1 | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-001 | 1 | 5 | 4 | 0 | 1 | 80% | UNVERIFIED | n/a |
| exact_statistics-002 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-003 | 1 | 2 | 1 | 0 | 1 | 50% | UNVERIFIED | n/a |
| single_game_narrative-001 | 1 | 44 | 42 | 0 | 2 | 95% | UNVERIFIED | n/a |
| single_game_narrative-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-003 | 1 | 58 | 13 | 0 | 45 | 22% | UNVERIFIED | n/a |
| single_game_narrative-006 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-009 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| turning_points-001 | 1 | 44 | 42 | 0 | 2 | 95% | UNVERIFIED | n/a |
| turning_points-002 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-003 | 1 | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| unsupported-001 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-002 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-003 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-004 | 1 | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-006 | 1 | 1 | 0 | 0 | 1 | 0% | UNVERIFIED | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 3 | 11 | 11 | 0 | 0 | 100% |
| comparisons | 6 | 34 | 34 | 0 | 0 | 100% |
| date_range_last_n | 5 | 20 | 19 | 0 | 1 | 95% |
| exact_statistics | 3 | 10 | 8 | 0 | 2 | 80% |
| single_game_narrative | 5 | 107 | 60 | 0 | 47 | 56% |
| turning_points | 3 | 92 | 88 | 0 | 4 | 96% |
| unsupported | 5 | 2 | 1 | 0 | 1 | 50% |

## Wrong numbers (0)

None.

## Unverified numbers (55)

- date_range_last_n-001: 1 unverified: `+12`
- exact_statistics-001: 1 unverified: `+519`
- exact_statistics-003: 1 unverified: `116.45121951219512`
- single_game_narrative-001: 2 unverified: `18`, `18`
- single_game_narrative-003: 45 unverified: `12-27`, `30-36`, `-6`, `128-125`, `+3`, `01-02`, `29-17`, `+12`, `99-111`, `-12`, `04-06`, `27-26` (+33 more)
- turning_points-001: 2 unverified: `18`, `18`
- turning_points-003: 2 unverified: `26`, `26`
- unsupported-006: 1 unverified: `2025–26`
