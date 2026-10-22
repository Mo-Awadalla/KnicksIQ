# Old audit versus replacement audit

Old verdicts are the claim-list audit at commit 5b585e6. Its numeric check counted only listed claims, and claims without an extractor compared a stored constant rather than the answer text.

| id | trial | old verdict | new verdict | found | wrong | unverified | change |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| aliases_typos-003 |  | n/a | UNVERIFIED | 21 | 0 | 16 | no old verdict |
| comparisons-002 |  | n/a | UNVERIFIED | 5 | 0 | 4 | no old verdict |
| comparisons-008 |  | n/a | INCORRECT | 5 | 1 | 3 | no old verdict |
| comparisons-010 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| date_range_last_n-005 |  | n/a | INCORRECT | 6 | 2 | 3 | no old verdict |
| single_game_narrative-004 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| turning_points-003 |  | n/a | UNVERIFIED | 43 | 0 | 2 | no old verdict |
| turning_points-007 |  | n/a | INCORRECT | 10 | 1 | 4 | no old verdict |

Verdict changes: 0. A downgrade means the old audit reported a pass for a response with numbers it did not check, or checked them against a constant. An old fail cleared means every number now recomputes.
