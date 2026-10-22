# Replacement factual audit: correctness acceptance

Responses: 36. Numeric atoms found: 124. Checked: 124 (100.00% coverage). Verified: 124. Wrong: 0. Unverified: 0.

Every numeric atom is extracted from the answer text, assigned a subject, phase, window, location, opponent and type from the surrounding sentence, and recomputed from raw restore tables by this audit's own SQL. An atom that no verifier can bind is UNVERIFIED and cannot pass.

## Per-response table

| id | trial | found | verified | wrong | unverified | coverage | verdict | old |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| aliases_typos-004 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| aliases_typos-004 | 2 | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| aliases_typos-006 | 1 | 6 | 6 | 0 | 0 | 100% | CORRECT | CORRECT |
| aliases_typos-006 | 2 | 5 | 5 | 0 | 0 | 100% | CORRECT | CORRECT |
| aliases_typos-009 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| aliases_typos-009 | 2 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| aliases_typos-010 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| aliases_typos-010 | 2 | 6 | 6 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| date_range_last_n-006 | 1 | 5 | 5 | 0 | 0 | 100% | CORRECT | CORRECT |
| date_range_last_n-006 | 2 | 5 | 5 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-001 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-001 | 2 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-002 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-002 | 2 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-003 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-003 | 2 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-004 | 1 | 2 | 2 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-004 | 2 | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-005 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-005 | 2 | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-006 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-006 | 2 | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-007 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-007 | 2 | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-008 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-008 | 2 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-009 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-009 | 2 | 3 | 3 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-010 | 1 | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| exact_statistics-010 | 2 | 4 | 4 | 0 | 0 | 100% | CORRECT | CORRECT |
| turning_points-003 | 1 | 3 | 3 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| turning_points-003 | 2 | 3 | 3 | 0 | 0 | 100% | CORRECT | DECLINE_MISSED_ANSWER |
| unsupported-006 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | DECLINE_APPROPRIATE |
| unsupported-006 | 2 | 5 | 5 | 0 | 0 | 100% | CORRECT | DECLINE_APPROPRIATE |
| unsupported-007 | 1 | 1 | 1 | 0 | 0 | 100% | CORRECT | DECLINE_APPROPRIATE |
| unsupported-007 | 2 | 1 | 1 | 0 | 0 | 100% | CORRECT | DECLINE_APPROPRIATE |

## By category

| category | responses | found | verified | wrong | unverified | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aliases_typos | 8 | 33 | 33 | 0 | 0 | 100% |
| date_range_last_n | 2 | 10 | 10 | 0 | 0 | 100% |
| exact_statistics | 20 | 67 | 67 | 0 | 0 | 100% |
| turning_points | 2 | 6 | 6 | 0 | 0 | 100% |
| unsupported | 4 | 8 | 8 | 0 | 0 | 100% |

## Wrong numbers (0)

None.

## Unverified numbers (0)

None.
