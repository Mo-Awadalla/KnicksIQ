# Old audit versus replacement audit

Old verdicts are the claim-list audit at commit 5b585e6. Its numeric check counted only listed claims, and claims without an extractor compared a stored constant rather than the answer text.

| id | trial | old verdict | new verdict | found | wrong | unverified | change |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| aliases_typos-001 | 1 | n/a | UNVERIFIED | 5 | 0 | 2 | no old verdict |
| aliases_typos-002 | 1 | n/a | UNVERIFIED | 12 | 0 | 3 | no old verdict |
| aliases_typos-003 | 1 | n/a | UNVERIFIED | 15 | 0 | 8 | no old verdict |
| aliases_typos-004 | 1 | n/a | CORRECT | 3 | 0 | 0 | no old verdict |
| aliases_typos-005 | 1 | n/a | CORRECT | 7 | 0 | 0 | no old verdict |
| aliases_typos-006 | 1 | n/a | UNVERIFIED | 16 | 0 | 5 | no old verdict |
| aliases_typos-007 | 1 | n/a | UNVERIFIED | 23 | 0 | 19 | no old verdict |
| aliases_typos-008 | 1 | n/a | CORRECT | 3 | 0 | 0 | no old verdict |
| aliases_typos-009 | 1 | n/a | CORRECT | 3 | 0 | 0 | no old verdict |
| aliases_typos-010 | 1 | n/a | UNVERIFIED | 43 | 0 | 3 | no old verdict |
| comparisons-001 | 1 | n/a | INCORRECT | 10 | 4 | 2 | no old verdict |
| comparisons-002 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| comparisons-003 | 1 | n/a | UNVERIFIED | 9 | 0 | 6 | no old verdict |
| comparisons-004 | 1 | n/a | UNVERIFIED | 13 | 0 | 7 | no old verdict |
| comparisons-005 | 1 | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| comparisons-006 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| comparisons-007 | 1 | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| comparisons-008 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| comparisons-009 | 1 | n/a | UNVERIFIED | 22 | 0 | 16 | no old verdict |
| comparisons-010 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| date_range_last_n-001 | 1 | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| date_range_last_n-002 | 1 | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| date_range_last_n-003 | 1 | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| date_range_last_n-004 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| date_range_last_n-005 | 1 | n/a | INCORRECT | 6 | 3 | 2 | no old verdict |
| date_range_last_n-006 | 1 | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| date_range_last_n-007 | 1 | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| date_range_last_n-008 | 1 | n/a | CORRECT | 2 | 0 | 0 | no old verdict |
| date_range_last_n-009 | 1 | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| date_range_last_n-010 | 1 | n/a | UNVERIFIED | 6 | 0 | 1 | no old verdict |
| exact_statistics-001 | 1 | n/a | UNVERIFIED | 5 | 0 | 1 | no old verdict |
| exact_statistics-002 | 1 | n/a | INCORRECT | 3 | 1 | 1 | no old verdict |
| exact_statistics-003 | 1 | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| exact_statistics-004 | 1 | n/a | INCORRECT | 3 | 1 | 1 | no old verdict |
| exact_statistics-005 | 1 | n/a | UNVERIFIED | 4 | 0 | 1 | no old verdict |
| exact_statistics-006 | 1 | n/a | INCORRECT | 4 | 2 | 1 | no old verdict |
| exact_statistics-007 | 1 | n/a | INCORRECT | 4 | 1 | 0 | no old verdict |
| exact_statistics-008 | 1 | n/a | UNVERIFIED | 8 | 0 | 4 | no old verdict |
| exact_statistics-009 | 1 | n/a | CORRECT | 3 | 0 | 0 | no old verdict |
| exact_statistics-010 | 1 | n/a | UNVERIFIED | 3 | 0 | 1 | no old verdict |
| single_game_narrative-001 | 1 | n/a | UNVERIFIED | 44 | 0 | 2 | no old verdict |
| single_game_narrative-002 | 1 | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| single_game_narrative-003 | 1 | n/a | UNVERIFIED | 71 | 0 | 50 | no old verdict |
| single_game_narrative-004 | 1 | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| single_game_narrative-005 | 1 | n/a | UNVERIFIED | 37 | 0 | 35 | no old verdict |
| single_game_narrative-006 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| single_game_narrative-007 | 1 | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| single_game_narrative-008 | 1 | n/a | CORRECT | 28 | 0 | 0 | no old verdict |
| single_game_narrative-009 | 1 | n/a | CORRECT | 8 | 0 | 0 | no old verdict |
| single_game_narrative-010 | 1 | n/a | UNVERIFIED | 6 | 0 | 2 | no old verdict |
| turning_points-001 | 1 | n/a | UNVERIFIED | 10 | 0 | 6 | no old verdict |
| turning_points-002 | 1 | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| turning_points-003 | 1 | n/a | UNVERIFIED | 16 | 0 | 4 | no old verdict |
| turning_points-004 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| turning_points-005 | 1 | n/a | INCORRECT | 13 | 1 | 7 | no old verdict |
| turning_points-006 | 1 | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| turning_points-007 | 1 | n/a | UNVERIFIED | 43 | 0 | 3 | no old verdict |
| turning_points-008 | 1 | n/a | UNVERIFIED | 50 | 0 | 3 | no old verdict |
| turning_points-009 | 1 | n/a | UNVERIFIED | 15 | 0 | 1 | no old verdict |
| turning_points-010 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-001 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-002 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-003 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-004 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-005 | 1 | n/a | CORRECT | 1 | 0 | 0 | no old verdict |
| unsupported-006 | 1 | n/a | CORRECT | 1 | 0 | 0 | no old verdict |
| unsupported-007 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-008 | 1 | n/a | INCORRECT | 3 | 2 | 0 | no old verdict |
| unsupported-009 | 1 | n/a | CORRECT | 2 | 0 | 0 | no old verdict |
| unsupported-010 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |

Verdict changes: 0. A downgrade means the old audit reported a pass for a response with numbers it did not check, or checked them against a constant. An old fail cleared means every number now recomputes.
