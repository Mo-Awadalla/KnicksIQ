# Old audit versus replacement audit

Old verdicts are the claim-list audit at commit 5b585e6. Its numeric check counted only listed claims, and claims without an extractor compared a stored constant rather than the answer text.

| id | trial | old verdict | new verdict | found | wrong | unverified | change |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| aliases_typos-001 |  | CORRECT | CORRECT | 13 | 0 | 0 | same |
| aliases_typos-002 |  | CORRECT | UNVERIFIED | 17 | 0 | 4 | old pass downgraded |
| aliases_typos-003 |  | UNSUPPORTED_CLAIM | NO_NUMBERS | 0 | 0 | 0 | changed |
| aliases_typos-004 |  | CORRECT | CORRECT | 21 | 0 | 0 | same |
| aliases_typos-005 |  | DECLINE_MISSED_ANSWER | NO_NUMBERS | 0 | 0 | 0 | changed |
| aliases_typos-006 |  | CORRECT | CORRECT | 7 | 0 | 0 | same |
| aliases_typos-007 |  | DECLINE_MISSED_ANSWER | CORRECT | 4 | 0 | 0 | changed |
| aliases_typos-008 |  | DECLINE_MISSED_ANSWER | NO_NUMBERS | 0 | 0 | 0 | changed |
| aliases_typos-009 |  | CORRECT | CORRECT | 3 | 0 | 0 | same |
| aliases_typos-010 |  | INCORRECT | CORRECT | 5 | 0 | 0 | old fail cleared |
| comparisons-001 |  | DECLINE_MISSED_ANSWER | CORRECT | 11 | 0 | 0 | changed |
| comparisons-002 |  | CORRECT | INCORRECT | 17 | 1 | 0 | old pass downgraded |
| comparisons-003 |  | DECLINE_MISSED_ANSWER | UNVERIFIED | 9 | 0 | 2 | old pass downgraded |
| comparisons-004 |  | DECLINE_MISSED_ANSWER | CORRECT | 2 | 0 | 0 | changed |
| comparisons-005 |  | DECLINE_MISSED_ANSWER | CORRECT | 2 | 0 | 0 | changed |
| comparisons-006 |  | DECLINE_MISSED_ANSWER | CORRECT | 10 | 0 | 0 | changed |
| comparisons-007 |  | UNSUPPORTED_CLAIM | UNVERIFIED | 33 | 0 | 1 | changed |
| comparisons-008 |  | CORRECT | CORRECT | 5 | 0 | 0 | same |
| comparisons-009 |  | DECLINE_MISSED_ANSWER | CORRECT | 21 | 0 | 0 | changed |
| comparisons-010 |  | DECLINE_MISSED_ANSWER | CORRECT | 5 | 0 | 0 | changed |
| date_range_last_n-001 |  | CORRECT | CORRECT | 6 | 0 | 0 | same |
| date_range_last_n-002 |  | CORRECT | CORRECT | 5 | 0 | 0 | same |
| date_range_last_n-003 |  | CORRECT | CORRECT | 9 | 0 | 0 | same |
| date_range_last_n-004 |  | CORRECT | CORRECT | 6 | 0 | 0 | same |
| date_range_last_n-005 |  | DECLINE_MISSED_ANSWER | CORRECT | 4 | 0 | 0 | changed |
| date_range_last_n-006 |  | CORRECT | CORRECT | 3 | 0 | 0 | same |
| date_range_last_n-007 |  | DECLINE_MISSED_ANSWER | CORRECT | 5 | 0 | 0 | changed |
| date_range_last_n-008 |  | DECLINE_MISSED_ANSWER | CORRECT | 2 | 0 | 0 | changed |
| date_range_last_n-009 |  | DECLINE_MISSED_ANSWER | INCORRECT | 4 | 4 | 0 | old pass downgraded |
| date_range_last_n-010 |  | DECLINE_MISSED_ANSWER | INCORRECT | 4 | 4 | 0 | old pass downgraded |
| exact_statistics-001 |  | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-002 |  | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-003 |  | CORRECT | CORRECT | 5 | 0 | 0 | same |
| exact_statistics-004 |  | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-005 |  | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-006 |  | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-007 |  | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-008 |  | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-009 |  | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-010 |  | CORRECT | CORRECT | 3 | 0 | 0 | same |
| single_game_narrative-001 |  | DECLINE_MISSED_ANSWER | UNVERIFIED | 11 | 0 | 2 | old pass downgraded |
| single_game_narrative-002 |  | CORRECT | NO_NUMBERS | 0 | 0 | 0 | changed |
| single_game_narrative-003 |  | DECLINE_MISSED_ANSWER | UNVERIFIED | 41 | 0 | 3 | old pass downgraded |
| single_game_narrative-004 |  | INSUFFICIENT | NO_NUMBERS | 0 | 0 | 0 | changed |
| single_game_narrative-005 |  | DECLINE_MISSED_ANSWER | CORRECT | 5 | 0 | 0 | changed |
| single_game_narrative-006 |  | DECLINE_MISSED_ANSWER | CORRECT | 10 | 0 | 0 | changed |
| single_game_narrative-007 |  | CORRECT | CORRECT | 4 | 0 | 0 | same |
| single_game_narrative-008 |  | DECLINE_MISSED_ANSWER | UNVERIFIED | 1 | 0 | 1 | old pass downgraded |
| single_game_narrative-009 |  | CORRECT | CORRECT | 8 | 0 | 0 | same |
| single_game_narrative-010 |  | DECLINE_APPROPRIATE | UNVERIFIED | 9 | 0 | 3 | old pass downgraded |
| turning_points-001 |  | DECLINE_MISSED_ANSWER | UNVERIFIED | 9 | 0 | 6 | old pass downgraded |
| turning_points-002 |  | CORRECT | CORRECT | 5 | 0 | 0 | same |
| turning_points-003 |  | DECLINE_MISSED_ANSWER | UNVERIFIED | 9 | 0 | 2 | old pass downgraded |
| turning_points-004 |  | CORRECT | CORRECT | 4 | 0 | 0 | same |
| turning_points-005 |  | DECLINE_MISSED_ANSWER | CORRECT | 11 | 0 | 0 | changed |
| turning_points-006 |  | CORRECT | CORRECT | 4 | 0 | 0 | same |
| turning_points-007 |  | DECLINE_MISSED_ANSWER | UNVERIFIED | 15 | 0 | 4 | old pass downgraded |
| turning_points-008 |  | DECLINE_MISSED_ANSWER | CORRECT | 4 | 0 | 0 | changed |
| turning_points-009 |  | DECLINE_MISSED_ANSWER | CORRECT | 15 | 0 | 0 | changed |
| turning_points-010 |  | CORRECT | CORRECT | 8 | 0 | 0 | same |
| unsupported-001 |  | DECLINE_APPROPRIATE | CORRECT | 1 | 0 | 0 | changed |
| unsupported-002 |  | DECLINE_APPROPRIATE | NO_NUMBERS | 0 | 0 | 0 | changed |
| unsupported-003 |  | DECLINE_APPROPRIATE | CORRECT | 1 | 0 | 0 | changed |
| unsupported-004 |  | DECLINE_APPROPRIATE | CORRECT | 1 | 0 | 0 | changed |
| unsupported-005 |  | DECLINE_APPROPRIATE | CORRECT | 1 | 0 | 0 | changed |
| unsupported-006 |  | DECLINE_APPROPRIATE | UNVERIFIED | 9 | 0 | 4 | old pass downgraded |
| unsupported-007 |  | DECLINE_APPROPRIATE | CORRECT | 1 | 0 | 0 | changed |
| unsupported-008 |  | UNSUPPORTED_CLAIM | CORRECT | 2 | 0 | 0 | changed |
| unsupported-009 |  | CORRECT | CORRECT | 2 | 0 | 0 | same |
| unsupported-010 |  | CORRECT | CORRECT | 4 | 0 | 0 | same |

Verdict changes: 14. A downgrade means the old audit reported a pass for a response with numbers it did not check, or checked them against a constant. An old fail cleared means every number now recomputes.
