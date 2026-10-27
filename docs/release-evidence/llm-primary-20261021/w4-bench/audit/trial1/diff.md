# Old audit versus replacement audit

Old verdicts are the claim-list audit at commit 5b585e6. Its numeric check counted only listed claims, and claims without an extractor compared a stored constant rather than the answer text.

| id | trial | old verdict | new verdict | found | wrong | unverified | change |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| aliases_typos-001 |  | n/a | UNVERIFIED | 5 | 0 | 1 | no old verdict |
| aliases_typos-002 |  | n/a | UNVERIFIED | 11 | 0 | 3 | no old verdict |
| aliases_typos-003 |  | n/a | INCORRECT | 3 | 2 | 0 | no old verdict |
| aliases_typos-004 |  | n/a | UNVERIFIED | 9 | 0 | 6 | no old verdict |
| aliases_typos-005 |  | n/a | CORRECT | 8 | 0 | 0 | no old verdict |
| aliases_typos-006 |  | n/a | UNVERIFIED | 13 | 0 | 6 | no old verdict |
| aliases_typos-007 |  | n/a | UNVERIFIED | 62 | 0 | 44 | no old verdict |
| aliases_typos-008 |  | n/a | UNVERIFIED | 10 | 0 | 9 | no old verdict |
| aliases_typos-009 |  | n/a | UNVERIFIED | 18 | 0 | 13 | no old verdict |
| aliases_typos-010 |  | n/a | UNVERIFIED | 10 | 0 | 4 | no old verdict |
| comparisons-001 |  | n/a | INCORRECT | 10 | 4 | 2 | no old verdict |
| comparisons-002 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| comparisons-003 |  | n/a | UNVERIFIED | 9 | 0 | 7 | no old verdict |
| comparisons-004 |  | n/a | INCORRECT | 11 | 2 | 6 | no old verdict |
| comparisons-005 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| comparisons-006 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| comparisons-007 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| comparisons-008 |  | n/a | UNVERIFIED | 5 | 0 | 4 | no old verdict |
| comparisons-009 |  | n/a | UNVERIFIED | 22 | 0 | 16 | no old verdict |
| comparisons-010 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| date_range_last_n-001 |  | n/a | UNVERIFIED | 10 | 0 | 4 | no old verdict |
| date_range_last_n-002 |  | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| date_range_last_n-003 |  | n/a | UNVERIFIED | 9 | 0 | 7 | no old verdict |
| date_range_last_n-004 |  | n/a | INCORRECT | 6 | 1 | 2 | no old verdict |
| date_range_last_n-005 |  | n/a | INCORRECT | 5 | 4 | 1 | no old verdict |
| date_range_last_n-006 |  | n/a | UNVERIFIED | 2 | 0 | 1 | no old verdict |
| date_range_last_n-007 |  | n/a | UNVERIFIED | 6 | 0 | 2 | no old verdict |
| date_range_last_n-008 |  | n/a | CORRECT | 2 | 0 | 0 | no old verdict |
| date_range_last_n-009 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| date_range_last_n-010 |  | n/a | UNVERIFIED | 6 | 0 | 1 | no old verdict |
| exact_statistics-001 |  | n/a | UNVERIFIED | 5 | 0 | 1 | no old verdict |
| exact_statistics-002 |  | n/a | CORRECT | 2 | 0 | 0 | no old verdict |
| exact_statistics-003 |  | n/a | UNVERIFIED | 4 | 0 | 1 | no old verdict |
| exact_statistics-004 |  | n/a | CORRECT | 6 | 0 | 0 | no old verdict |
| exact_statistics-005 |  | n/a | UNVERIFIED | 4 | 0 | 1 | no old verdict |
| exact_statistics-006 |  | n/a | UNVERIFIED | 4 | 0 | 1 | no old verdict |
| exact_statistics-007 |  | n/a | UNVERIFIED | 4 | 0 | 1 | no old verdict |
| exact_statistics-008 |  | n/a | INCORRECT | 6 | 1 | 1 | no old verdict |
| exact_statistics-009 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| exact_statistics-010 |  | n/a | UNVERIFIED | 4 | 0 | 1 | no old verdict |
| single_game_narrative-001 |  | n/a | UNVERIFIED | 15 | 0 | 1 | no old verdict |
| single_game_narrative-002 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| single_game_narrative-003 |  | n/a | INCORRECT | 58 | 2 | 47 | no old verdict |
| single_game_narrative-004 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| single_game_narrative-005 |  | n/a | UNVERIFIED | 37 | 0 | 35 | no old verdict |
| single_game_narrative-006 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| single_game_narrative-007 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| single_game_narrative-008 |  | n/a | CORRECT | 28 | 0 | 0 | no old verdict |
| single_game_narrative-009 |  | n/a | CORRECT | 8 | 0 | 0 | no old verdict |
| single_game_narrative-010 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| turning_points-001 |  | n/a | UNVERIFIED | 8 | 0 | 5 | no old verdict |
| turning_points-002 |  | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| turning_points-003 |  | n/a | UNVERIFIED | 43 | 0 | 2 | no old verdict |
| turning_points-004 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| turning_points-005 |  | n/a | INCORRECT | 13 | 1 | 8 | no old verdict |
| turning_points-006 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| turning_points-007 |  | n/a | CORRECT | 9 | 0 | 0 | no old verdict |
| turning_points-008 |  | n/a | INCORRECT | 18 | 1 | 5 | no old verdict |
| turning_points-009 |  | n/a | INCORRECT | 13 | 1 | 7 | no old verdict |
| turning_points-010 |  | n/a | CORRECT | 8 | 0 | 0 | no old verdict |
| unsupported-001 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-002 |  | n/a | CORRECT | 1 | 0 | 0 | no old verdict |
| unsupported-003 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-004 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-005 |  | n/a | CORRECT | 1 | 0 | 0 | no old verdict |
| unsupported-006 |  | n/a | CORRECT | 1 | 0 | 0 | no old verdict |
| unsupported-007 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-008 |  | n/a | INCORRECT | 3 | 2 | 0 | no old verdict |
| unsupported-009 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-010 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |

Verdict changes: 0. A downgrade means the old audit reported a pass for a response with numbers it did not check, or checked them against a constant. An old fail cleared means every number now recomputes.
