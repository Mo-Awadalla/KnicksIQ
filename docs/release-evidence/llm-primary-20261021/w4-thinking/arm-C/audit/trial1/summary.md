# Replacement factual audit: arm C trial 1

Responses: 30. Numeric atoms found: 292. Checked: 200 (68.49% coverage). Verified: 200. Wrong: 0. Unverified: 92.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-001 |  | 7 | 6 | 0 | 1 | 86% | UNVERIFIED | n/a |
| aliases_typos-002 |  | 16 | 7 | 0 | 9 | 44% | UNVERIFIED | n/a |
| aliases_typos-003 |  | 35 | 7 | 0 | 28 | 20% | UNVERIFIED | n/a |
| comparisons-001 |  | 10 | 10 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-003 |  | 11 | 7 | 0 | 4 | 64% | UNVERIFIED | n/a |
| comparisons-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| comparisons-007 |  | 4 | 4 | 0 | 0 | 100% | CORRECT | n/a |
| comparisons-010 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| date_range_last_n-001 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-003 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-005 |  | 6 | 6 | 0 | 0 | 100% | CORRECT | n/a |
| date_range_last_n-008 |  | 2 | 2 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-001 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-002 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| exact_statistics-003 |  | 3 | 3 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-001 |  | 15 | 14 | 0 | 1 | 93% | UNVERIFIED | n/a |
| single_game_narrative-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| single_game_narrative-003 |  | 58 | 13 | 0 | 45 | 22% | UNVERIFIED | n/a |
| single_game_narrative-006 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| single_game_narrative-009 |  | 8 | 8 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-001 |  | 44 | 42 | 0 | 2 | 95% | UNVERIFIED | n/a |
| turning_points-002 |  | 5 | 5 | 0 | 0 | 100% | CORRECT | n/a |
| turning_points-003 |  | 43 | 41 | 0 | 2 | 95% | UNVERIFIED | n/a |
| unsupported-001 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-002 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-003 |  | 0 | 0 | 0 | 0 | n/a | NO_NUMBERS | n/a |
| unsupported-004 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |
| unsupported-006 |  | 1 | 1 | 0 | 0 | 100% | CORRECT | n/a |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 3 | 58 | 20 | 0 | 38 | 34% |
| comparisons | 6 | 25 | 21 | 0 | 4 | 84% |
| date_range_last_n | 5 | 18 | 18 | 0 | 0 | 100% |
| exact_statistics | 3 | 11 | 11 | 0 | 0 | 100% |
| single_game_narrative | 5 | 86 | 40 | 0 | 46 | 47% |
| turning_points | 3 | 92 | 88 | 0 | 4 | 96% |
| unsupported | 5 | 2 | 2 | 0 | 0 | 100% |

## Wrong numbers (0)

None.

## Unverified numbers (92)

- aliases_typos-001: 1 unverified: `103.25`
- aliases_typos-002: 9 unverified: `+32`, `105`, `95`, `123`, `117`, `111`, `89`, `112`, `106`
- aliases_typos-003: 28 unverified: `37`, `5`, `7`, `3`, `33`, `3`, `11`, `2`, `40`, `4`, `8`, `2` (+16 more)
- comparisons-003: 4 unverified: `+19.60`, `111.25`, `+8.00`, `4`
- single_game_narrative-001: 1 unverified: `14`
- single_game_narrative-003: 45 unverified: `12-27`, `30-36`, `-6`, `128-125`, `+3`, `01-02`, `29-17`, `+12`, `99-111`, `-12`, `04-06`, `27-26` (+33 more)
- turning_points-001: 2 unverified: `18`, `18`
- turning_points-003: 2 unverified: `26`, `26`
