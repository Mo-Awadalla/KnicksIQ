# Reproduction before the fix (deterministic, no provider)

Captured with the same `repro.py` on `codex/llmp-integration` before the fix commits.

| id | resolved scope | observed answer |
| --- | --- | --- |
| date_range_last_n-006 | away, December, `game_result=W`, 5 game ids | `Knicks wins: 5 over 5`, `losses: 0 over 5` |
| exact_statistics-008 | `game_result=W`, one game id | `wins 1, losses 0, points 120` |
| aliases_typos-004 | Towns + TOR, 5 game ids | tool: 17.4 over 5; live model answered one 2026-03-03 game as "a single observed appearance" |
| aliases_typos-009 | Anunoby + BOS, 4 game ids | status `incomplete_coverage`, limitation "Missing player rows for archived game IDs [20, 53]" |
| unsupported-007 | wins only, 69 game ids | live model said latest game is 2025-12-21 |
| exact_statistics-009 | `game_result=L`, 32 game ids | `wins 0, losses 32, points 3421` |
| exact_statistics-010 | all-phase, no extreme | `wins 69, losses 32, points 11750` |
| turning_points-003 | ATL, all phases | `wins 6, losses 3, points 1042` |
| aliases_typos-010 | all-phase | `wins 69, losses 32, points 11750` |
| exact_statistics-001 | all-phase | `wins 69, losses 32` |
| unsupported-006 | all-phase | `wins 69, losses 32, points 11750` |

`repro-after/` holds the post-fix output for the same script and questions.
