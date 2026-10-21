# Correctness defects: reproduction, root cause, fix

Deterministic reproduction (no provider): `repro.py` -> `repro-before.json`.
Live acceptance: `run_ids.py` over the audited ids, then the factual audit with
`checks_policy_20261021.py` (SQL oracle from `queries_core.sql`).

## 1. Count of wins filtered the population (date_range_last_n-006, exact_statistics-008)

Failure: `How many road games did they win in December?` resolved `game_result=W`, so the
population became the five wins: the answer said `5-0 across 5 games` instead of `5-3 in 8`.
`biggest win by margin` leaked `0 losses in that filtered set`.

Root cause: `resolve_query` set `game_result` from any occurrence of `win/loss`. That word is
the thing being counted, not a subset selector.

Fix: `is_outcome_subset` in `query_resolution.py` only sets `game_result` for explicit subsets
(`in wins`, `only losses`, `won games`, `when they win`). Count/record/yes-no questions keep
the full population. Team extremes now return one extreme claim instead of aggregate artifacts.

## 2. Season phase default was inconsistent (aliases_typos-004, seven exact_statistics passes)

Failure: season-level answers used all-phase totals (`69-32`, `11,750`, `7.94`) while a fan
asking "this season" expects the regular season; a matchup answer claimed a single Towns
appearance against Toronto while five exist.

Root cause: `season_type` stayed `None` unless a phase word appeared, so every population was
all-phase. Statements did not name a phase, so the model filled the gap with the wrong reading.

Fix: `resolve_query` defaults season-level questions (no opponent, date window, or relative
window) to `regular`; `overall`/`including playoffs`/`all phases` explicitly mean all phases;
opponent questions stay all-phase. Team/player statements name the phase and opponent
breakdowns are emitted as separate claims.

## 3. Player absence reported as a coverage gap (aliases_typos-009)

Failure: `How did OG look vs the C's?` said player rows were missing for two games; both games
had complete NYK player rows, Anunoby simply did not appear.

Root cause: `analyst_calculations.player` treated any game without a row for the player as an
unknown-coverage gap, conflating DNP with missing data.

Fix: a game with other NYK player rows but no row for the player is an observed non-appearance
(limitation text, status ok). Only a game with no NYK player rows at all is incomplete coverage.

## 4. False latest date (unsupported-007)

Failure: `Did the Knicks win yesterday?` declined but stated the latest game as `2025-12-21`;
the release ends `2026-06-13`.

Root cause: the manifest had no archive date range, so the model inferred recency from a
single-game discovery claim (Brunson's 47-point game).

Fix: `manifest()` exposes `date_range.first_game_date/last_game_date`; orchestrator and
reviewer prompts require recency claims to match it. Live fallback for live/current questions
states the real latest date instead of reusing aggregates.

## 5. Fallback dumped unrelated aggregates (exact_statistics-009/010, turning_points-003, aliases_typos-010, unsupported-006)

Failure: failed turns answered with `Knicks wins/losses/points` totals for questions about
extremes, collapses, or conference standings.

Root cause: `fallback_claims` only checked subject and population, not whether the metric
answered the question.

Fix: `analyst_fallback` classifies the question (live, discovery, extreme, record, matchup,
player, points, margin) and keeps only matching claims. No match -> a plain coverage decline.
Team tool now answers `biggest win`, `worst loss by margin`, and `highest-scoring game` as
single-game extreme claims; matchup fallback includes regular-season and playoff breakdowns.

## 6. Capability text hardcoded the archive as scores only (unsupported.md findings)

Failure: answers claimed the archive has no play-by-play, quarter, or halftime data, and the
dispatch message said calculations support full-game box scores only.

Root cause: `manifest().data_types` was a hardcoded three-item list; the dispatch message was a
hardcoded string.

Fix: `ToolSpec.data_types` and `supports_periods` feed `capability_data_types()`; dispatch names
the period-capable tools from the registry. False blanket data-type limitations are no longer
supported by the capabilities the model and reviewer see.

## 7. Two benchmark labels contradicted the archive (unsupported-009/010)

SQL: two Lakers games (`2026-02-01`, `2026-03-08`) and four Celtics games (`2025-10-24`,
`2025-12-02`, `2026-02-08`, `2026-04-09`) are in the active release, so asking which game is
the correct behavior. `answerable` corrected to true in `questions.jsonl`.
