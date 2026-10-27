# Old audit versus replacement audit

Old verdicts are the claim-list audit at commit 5b585e6. Its numeric check counted only listed claims, and claims without an extractor compared a stored constant rather than the answer text.

| id | trial | old verdict | new verdict | found | wrong | unverified | change |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| aliases_typos-001 | 1 | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| aliases_typos-002 | 1 | n/a | UNVERIFIED | 16 | 0 | 9 | no old verdict |
| aliases_typos-003 | 1 | n/a | UNVERIFIED | 31 | 0 | 20 | no old verdict |
| comparisons-001 | 1 | n/a | CORRECT | 10 | 0 | 0 | no old verdict |
| comparisons-002 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| comparisons-003 | 1 | n/a | UNVERIFIED | 9 | 0 | 2 | no old verdict |
| comparisons-006 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| comparisons-007 | 1 | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| comparisons-010 | 1 | n/a | INCORRECT | 4 | 2 | 2 | no old verdict |
| date_range_last_n-001 | 1 | n/a | CORRECT | 6 | 0 | 0 | no old verdict |
| date_range_last_n-002 | 1 | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| date_range_last_n-003 | 1 | n/a | UNVERIFIED | 9 | 0 | 8 | no old verdict |
| date_range_last_n-005 | 1 | n/a | CORRECT | 6 | 0 | 0 | no old verdict |
| date_range_last_n-008 | 1 | n/a | CORRECT | 2 | 0 | 0 | no old verdict |
| exact_statistics-001 | 1 | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| exact_statistics-002 | 1 | n/a | CORRECT | 3 | 0 | 0 | no old verdict |
| exact_statistics-003 | 1 | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| single_game_narrative-001 | 1 | n/a | INCORRECT | 12 | 1 | 6 | no old verdict |
| single_game_narrative-002 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| single_game_narrative-003 | 1 | n/a | UNVERIFIED | 58 | 0 | 45 | no old verdict |
| single_game_narrative-006 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| single_game_narrative-009 | 1 | n/a | CORRECT | 8 | 0 | 0 | no old verdict |
| turning_points-001 | 1 | n/a | INCORRECT | 7 | 1 | 4 | no old verdict |
| turning_points-002 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| turning_points-003 | 1 | n/a | UNVERIFIED | 43 | 0 | 2 | no old verdict |
| unsupported-001 | 1 | n/a | CORRECT | 1 | 0 | 0 | no old verdict |
| unsupported-002 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-003 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-004 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| unsupported-006 | 1 | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |

Verdict changes: 0. A downgrade means the old audit reported a pass for a response with numbers it did not check, or checked them against a constant. An old fail cleared means every number now recomputes.
