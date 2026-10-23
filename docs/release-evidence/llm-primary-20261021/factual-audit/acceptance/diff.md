# Old audit versus replacement audit

Old verdicts are the claim-list audit at commit 5b585e6. Its numeric check counted only listed claims, and claims without an extractor compared a stored constant rather than the answer text.

| id | trial | old verdict | new verdict | found | wrong | unverified | change |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| aliases_typos-004 | 1 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| aliases_typos-004 | 2 | CORRECT | CORRECT | 4 | 0 | 0 | same |
| aliases_typos-006 | 1 | CORRECT | CORRECT | 6 | 0 | 0 | same |
| aliases_typos-006 | 2 | CORRECT | CORRECT | 5 | 0 | 0 | same |
| aliases_typos-009 | 1 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| aliases_typos-009 | 2 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| aliases_typos-010 | 1 | DECLINE_MISSED_ANSWER | CORRECT | 3 | 0 | 0 | changed |
| aliases_typos-010 | 2 | DECLINE_MISSED_ANSWER | CORRECT | 6 | 0 | 0 | changed |
| date_range_last_n-006 | 1 | CORRECT | CORRECT | 5 | 0 | 0 | same |
| date_range_last_n-006 | 2 | CORRECT | CORRECT | 5 | 0 | 0 | same |
| exact_statistics-001 | 1 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-001 | 2 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-002 | 1 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-002 | 2 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-003 | 1 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-003 | 2 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-004 | 1 | CORRECT | CORRECT | 2 | 0 | 0 | same |
| exact_statistics-004 | 2 | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-005 | 1 | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-005 | 2 | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-006 | 1 | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-006 | 2 | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-007 | 1 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-007 | 2 | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-008 | 1 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-008 | 2 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-009 | 1 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-009 | 2 | CORRECT | CORRECT | 3 | 0 | 0 | same |
| exact_statistics-010 | 1 | CORRECT | CORRECT | 4 | 0 | 0 | same |
| exact_statistics-010 | 2 | CORRECT | CORRECT | 4 | 0 | 0 | same |
| turning_points-003 | 1 | DECLINE_MISSED_ANSWER | CORRECT | 3 | 0 | 0 | changed |
| turning_points-003 | 2 | DECLINE_MISSED_ANSWER | CORRECT | 3 | 0 | 0 | changed |
| unsupported-006 | 1 | DECLINE_APPROPRIATE | CORRECT | 1 | 0 | 0 | changed |
| unsupported-006 | 2 | DECLINE_APPROPRIATE | CORRECT | 5 | 0 | 0 | changed |
| unsupported-007 | 1 | DECLINE_APPROPRIATE | CORRECT | 1 | 0 | 0 | changed |
| unsupported-007 | 2 | DECLINE_APPROPRIATE | CORRECT | 1 | 0 | 0 | changed |

Verdict changes: 0. A downgrade means the old audit reported a pass for a response with numbers it did not check, or checked them against a constant. An old fail cleared means every number now recomputes.
