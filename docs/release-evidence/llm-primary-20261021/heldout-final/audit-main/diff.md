# Old audit versus replacement audit
Frozen code SHA: `51f184a23645f1d43f930a520a1cc053397a315b`.

Old verdicts are the claim-list audit at commit 5b585e6. Its numeric check counted only listed claims, and claims without an extractor compared a stored constant rather than the answer text.

| id | trial | old verdict | new verdict | found | wrong | unverified | change |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| heldout2-aliases_typos-001 |  | n/a | CORRECT | 12 | 0 | 0 | no old verdict |
| heldout2-aliases_typos-002 |  | n/a | UNVERIFIED | 5 | 0 | 1 | no old verdict |
| heldout2-aliases_typos-003 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-aliases_typos-004 |  | n/a | UNVERIFIED | 3 | 0 | 2 | no old verdict |
| heldout2-aliases_typos-005 |  | n/a | UNVERIFIED | 7 | 0 | 1 | no old verdict |
| heldout2-aliases_typos-006 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-aliases_typos-007 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-aliases_typos-008 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-aliases_typos-009 |  | n/a | UNVERIFIED | 4 | 0 | 1 | no old verdict |
| heldout2-aliases_typos-010 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| heldout2-aliases_typos-011 |  | n/a | INCORRECT | 3 | 1 | 0 | no old verdict |
| heldout2-comparisons-001 |  | n/a | UNVERIFIED | 5 | 0 | 4 | no old verdict |
| heldout2-comparisons-002 |  | n/a | UNVERIFIED | 10 | 0 | 5 | no old verdict |
| heldout2-comparisons-003 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-comparisons-004 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-comparisons-005 |  | n/a | INCORRECT | 3 | 2 | 1 | no old verdict |
| heldout2-comparisons-006 |  | n/a | UNVERIFIED | 5 | 0 | 4 | no old verdict |
| heldout2-comparisons-007 |  | n/a | UNVERIFIED | 5 | 0 | 4 | no old verdict |
| heldout2-comparisons-008 |  | n/a | INCORRECT | 4 | 3 | 1 | no old verdict |
| heldout2-comparisons-009 |  | n/a | UNVERIFIED | 3 | 0 | 2 | no old verdict |
| heldout2-comparisons-010 |  | n/a | UNVERIFIED | 8 | 0 | 1 | no old verdict |
| heldout2-comparisons-011 |  | n/a | INCORRECT | 2 | 2 | 0 | no old verdict |
| heldout2-date_range_last_n-001 |  | n/a | CORRECT | 5 | 0 | 0 | no old verdict |
| heldout2-date_range_last_n-002 |  | n/a | INCORRECT | 9 | 1 | 6 | no old verdict |
| heldout2-date_range_last_n-003 |  | n/a | INCORRECT | 4 | 3 | 0 | no old verdict |
| heldout2-date_range_last_n-004 |  | n/a | INCORRECT | 5 | 4 | 0 | no old verdict |
| heldout2-date_range_last_n-005 |  | n/a | INCORRECT | 2 | 2 | 0 | no old verdict |
| heldout2-date_range_last_n-006 |  | n/a | UNVERIFIED | 3 | 0 | 3 | no old verdict |
| heldout2-date_range_last_n-007 |  | n/a | CORRECT | 6 | 0 | 0 | no old verdict |
| heldout2-date_range_last_n-008 |  | n/a | INCORRECT | 2 | 1 | 1 | no old verdict |
| heldout2-date_range_last_n-009 |  | n/a | INCORRECT | 5 | 4 | 0 | no old verdict |
| heldout2-date_range_last_n-010 |  | n/a | INCORRECT | 4 | 4 | 0 | no old verdict |
| heldout2-date_range_last_n-011 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| heldout2-date_range_last_n-012 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| heldout2-exact_statistics-001 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| heldout2-exact_statistics-002 |  | n/a | CORRECT | 3 | 0 | 0 | no old verdict |
| heldout2-exact_statistics-003 |  | n/a | INCORRECT | 4 | 1 | 1 | no old verdict |
| heldout2-exact_statistics-004 |  | n/a | CORRECT | 2 | 0 | 0 | no old verdict |
| heldout2-exact_statistics-005 |  | n/a | UNVERIFIED | 4 | 0 | 2 | no old verdict |
| heldout2-exact_statistics-006 |  | n/a | UNVERIFIED | 11 | 0 | 3 | no old verdict |
| heldout2-exact_statistics-007 |  | n/a | UNVERIFIED | 3 | 0 | 2 | no old verdict |
| heldout2-exact_statistics-008 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-exact_statistics-009 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-exact_statistics-010 |  | n/a | CORRECT | 2 | 0 | 0 | no old verdict |
| heldout2-exact_statistics-011 |  | n/a | CORRECT | 4 | 0 | 0 | no old verdict |
| heldout2-exact_statistics-012 |  | n/a | UNVERIFIED | 3 | 0 | 2 | no old verdict |
| heldout2-single_game_narrative-001 |  | n/a | INCORRECT | 9 | 1 | 3 | no old verdict |
| heldout2-single_game_narrative-002 |  | n/a | UNVERIFIED | 8 | 0 | 2 | no old verdict |
| heldout2-single_game_narrative-003 |  | n/a | UNVERIFIED | 8 | 0 | 2 | no old verdict |
| heldout2-single_game_narrative-004 |  | n/a | UNVERIFIED | 15 | 0 | 8 | no old verdict |
| heldout2-single_game_narrative-005 |  | n/a | UNVERIFIED | 4 | 0 | 1 | no old verdict |
| heldout2-single_game_narrative-006 |  | n/a | UNVERIFIED | 3 | 0 | 1 | no old verdict |
| heldout2-single_game_narrative-007 |  | n/a | UNVERIFIED | 4 | 0 | 1 | no old verdict |
| heldout2-single_game_narrative-008 |  | n/a | UNVERIFIED | 5 | 0 | 1 | no old verdict |
| heldout2-single_game_narrative-009 |  | n/a | UNVERIFIED | 5 | 0 | 3 | no old verdict |
| heldout2-single_game_narrative-010 |  | n/a | CORRECT | 3 | 0 | 0 | no old verdict |
| heldout2-single_game_narrative-011 |  | n/a | UNVERIFIED | 3 | 0 | 1 | no old verdict |
| heldout2-turning_points-001 |  | n/a | INCORRECT | 14 | 1 | 7 | no old verdict |
| heldout2-turning_points-002 |  | n/a | INCORRECT | 22 | 3 | 11 | no old verdict |
| heldout2-turning_points-003 |  | n/a | UNVERIFIED | 18 | 0 | 10 | no old verdict |
| heldout2-turning_points-004 |  | n/a | UNVERIFIED | 14 | 0 | 5 | no old verdict |
| heldout2-turning_points-005 |  | n/a | UNVERIFIED | 17 | 0 | 11 | no old verdict |
| heldout2-turning_points-006 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-turning_points-007 |  | n/a | UNVERIFIED | 14 | 0 | 8 | no old verdict |
| heldout2-turning_points-008 |  | n/a | UNVERIFIED | 5 | 0 | 2 | no old verdict |
| heldout2-turning_points-009 |  | n/a | UNVERIFIED | 10 | 0 | 7 | no old verdict |
| heldout2-turning_points-010 |  | n/a | UNVERIFIED | 17 | 0 | 11 | no old verdict |
| heldout2-turning_points-011 |  | n/a | UNVERIFIED | 14 | 0 | 8 | no old verdict |
| heldout2-unsupported-001 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-unsupported-002 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-unsupported-003 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-unsupported-004 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-unsupported-005 |  | n/a | CORRECT | 1 | 0 | 0 | no old verdict |
| heldout2-unsupported-006 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-unsupported-007 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-unsupported-008 |  | n/a | UNVERIFIED | 2 | 0 | 1 | no old verdict |
| heldout2-unsupported-009 |  | n/a | CORRECT | 1 | 0 | 0 | no old verdict |
| heldout2-unsupported-010 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |
| heldout2-unsupported-011 |  | n/a | CORRECT | 1 | 0 | 0 | no old verdict |
| heldout2-unsupported-012 |  | n/a | NO_NUMBERS | 0 | 0 | 0 | no old verdict |

Verdict changes: 0. A downgrade means the old audit reported a pass for a response with numbers it did not check, or checked them against a constant. An old fail cleared means every number now recomputes.
