# Old audit versus replacement audit

Old verdicts are the claim-list audit at commit 5b585e6. Its numeric check counted only listed claims, and claims without an extractor compared a stored constant rather than the answer text.

| id | trial | old verdict | new verdict | found | wrong | unverified | change |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| aliases_typos-001 |  | n/a | CORRECT | 6 | 0 | 0 | no old verdict |
| aliases_typos-002 |  | n/a | UNVERIFIED | 16 | 0 | 1 | no old verdict |
| aliases_typos-003 |  | n/a | UNVERIFIED | 35 | 0 | 28 | no old verdict |
| comparisons-001 |  | n/a | CORRECT | 10 | 0 | 0 | no old verdict |
| comparisons-002 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| comparisons-003 |  | n/a | UNVERIFIED | 9 | 0 | 2 | no old verdict |
| comparisons-006 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| comparisons-007 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| comparisons-010 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| date_range_last_n-001 |  | n/a | CORRECT | 6 | 0 | 0 | no old verdict |
| date_range_last_n-002 |  | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| date_range_last_n-003 |  | n/a | CORRECT | 3 | 0 | 0 | no old verdict |
| date_range_last_n-005 |  | n/a | UNVERIFIED | 6 | 0 | 1 | no old verdict |
| date_range_last_n-008 |  | n/a | CORRECT | 2 | 0 | 0 | no old verdict |
| exact_statistics-001 |  | n/a | UNVERIFIED | 5 | 0 | 1 | no old verdict |
| exact_statistics-002 |  | n/a | UNVERIFIED | 3 | 0 | 1 | no old verdict |
| exact_statistics-003 |  | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| single_game_narrative-001 |  | n/a | UNVERIFIED | 10 | 0 | 2 | no old verdict |
| single_game_narrative-002 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| single_game_narrative-003 |  | n/a | UNVERIFIED | 58 | 0 | 45 | no old verdict |
| single_game_narrative-006 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| single_game_narrative-009 |  | n/a | CORRECT | 8 | 0 | 0 | no old verdict |
| turning_points-001 |  | n/a | UNVERIFIED | 44 | 0 | 2 | no old verdict |
| turning_points-002 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| turning_points-003 |  | n/a | UNVERIFIED | 16 | 0 | 2 | no old verdict |
| unsupported-001 |  | n/a | CORRECT | 1 | 0 | 0 | no old verdict |
| unsupported-002 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-003 |  | n/a | CORRECT | 1 | 0 | 0 | no old verdict |
| unsupported-004 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-006 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |

Verdict changes: 0. A downgrade means the old audit reported a pass for a response with numbers it did not check, or checked them against a constant. An old fail cleared means every number now recomputes.
