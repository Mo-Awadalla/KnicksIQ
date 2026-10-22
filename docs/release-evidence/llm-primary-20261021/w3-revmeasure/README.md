# Reviewer false acceptance: method and gate proof

Status: the live reviewer count is pending. The OpenRouter account behind `AI_API_KEY`
exhausted its credits (HTTP 402) before this measurement ran. The offline half is complete:
21 wrong answers across seven classes were constructed and each was proven to pass the
deterministic gate with zero `review_issues`. Controls are the 14 recorded correct answers.

Artifacts:

- `gate-proof.json`: every control and mutation, the exact answer text, and the recorded
  `review_issues` output (all empty). Regenerate with `--gate-only`.
- `false-acceptance.json` and `summary.md`: produced by the live run, not present yet.
- Script: `tools/release/reviewer_false_acceptance.py` (runner, recorder, statistics) and
  `tools/release/reviewer_false_acceptance_cases.py` (the 21 mutations).

## Why each class passes the gate

`review_issues` checks that every number token equals a supplied claim value, receipt
number or capability number. It matches values, not meaning: subjects, metric ids, units,
filters, phases and causal language are invisible to it. Each mutation below keeps every
number inside the trusted set.

| class | mutation | why the gate passes |
| --- | --- | --- |
| number_swapped_other_metric | Replace a metric value with another metric's trusted value (for example 116.34 ppg becomes 7.94, the margin per game). | `numeric_issues` compares Decimal values only; 7.94 is a supplied claim value. |
| wrong_subject | Move the right number to the wrong player or opponent (Brunson and Towns swapped, Knicks becomes Celtics). | Numbers are unchanged and remain supplied claim values; the gate has no subject check. |
| wrong_phase_or_window | Change home to road, road to home, or playoffs to regular season. | Numbers are unchanged and trusted; filters and `season_type` are reviewer-visible, not gate-checked. |
| wins_losses_swapped | Write 32-69 instead of 69-32, 1-4 instead of 4-1, 8-7 instead of 7-8. | Both numbers are supplied claim values; the gate checks presence, not order or meaning. |
| per_game_total_confusion | Say 116.34 total points instead of per game, or 11,750 per game instead of total. | The value is unchanged and trusted; the gate does not inspect units. |
| unsupported_causal_or_ranking | Append a causal or ranking sentence with no numbers ("proves their defense is the best in the league"). | `numeric_issues` has no token to check; declared claim references are unchanged. |
| coincident_percent | State 37%, 32% or 93%, each equal to an unrelated trusted integer (wins, losses, sample size). | `_explained` accepts the percent by value equality before any percent conversion. |

## Cases

| case | class | unit |
| --- | --- | --- |
| metric_swap_ppg_to_margin | number_swapped_other_metric | exact_statistics-003 |
| metric_swap_total_points_to_margin | number_swapped_other_metric | exact_statistics-002 |
| metric_swap_margin_to_ppg | number_swapped_other_metric | exact_statistics-004 |
| subject_swap_scorers | wrong_subject | comparisons-002 |
| subject_swap_brunson_to_towns | wrong_subject | date_range_last_n-003 |
| subject_swap_knicks_to_celtics | wrong_subject | exact_statistics-005 |
| phase_home_to_road | wrong_phase_or_window | exact_statistics-005 |
| phase_playoffs_to_regular | wrong_phase_or_window | date_range_last_n-003 |
| phase_road_to_home | wrong_phase_or_window | exact_statistics-006 |
| record_swap_season | wins_losses_swapped | exact_statistics-001 |
| record_swap_last_five | wins_losses_swapped | date_range_last_n-001 |
| record_swap_january | wins_losses_swapped | date_range_last_n-004 |
| unit_per_game_as_total | per_game_total_confusion | exact_statistics-003 |
| unit_total_as_per_game | per_game_total_confusion | exact_statistics-002 |
| unit_window_ppg_as_total | per_game_total_confusion | date_range_last_n-002 |
| causal_defense_ranking | unsupported_causal_or_ranking | exact_statistics-001 |
| causal_offense_ranking | unsupported_causal_or_ranking | comparisons-002 |
| causal_schedule_ranking | unsupported_causal_or_ranking | date_range_last_n-004 |
| percent_from_wins_value | coincident_percent | exact_statistics-005 |
| percent_from_losses_value | coincident_percent | exact_statistics-007 |
| percent_from_sample_size | coincident_percent | comparisons-002 |

## Pending live table

Two trials per case, 14 controls and 21 mutations (70 reviewer calls, 140 if every call
needs one malformed-JSON retry). Acceptance counts, Wilson intervals, cost and the upstream
provider per call will populate this table.

| class | accepted / trials | Wilson 95% | cost USD | providers |
| --- | --- | --- | ---: | --- |
| number_swapped_other_metric | pending | pending | pending | pending |
| wrong_subject | pending | pending | pending | pending |
| wrong_phase_or_window | pending | pending | pending | pending |
| wins_losses_swapped | pending | pending | pending | pending |
| per_game_total_confusion | pending | pending | pending | pending |
| unsupported_causal_or_ranking | pending | pending | pending | pending |
| coincident_percent | pending | pending | pending | pending |
| controls | pending | pending | pending | pending |

## Pending command

```bash
cd ~/.local/share/knicksiq/worktrees/revmeasure
set -a
. <(grep -E '^(AI_API_KEY|OPENROUTER_API_KEY|AI_BASE_URL|AI_CHAT_MODEL|AI_PROVIDER|AI_REQUEST_TIMEOUT_SECONDS)=' \
  /Users/mohamedawadalla/Projects/KnicksIQ/.env)
set +a
export DB_URL='postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq'
export REDIS_URL='redis://localhost:56500/1' AI_REASONING_EFFORT=none
export OPENROUTER_MONTHLY_CUTOFF_USD=2 ANALYSIS_ANSWER_MODE=llm_primary
export ANALYST_EVIDENCE_LOOP_ENABLED=true RAG_QDRANT_ENABLED=false TEST_MODE=false
uv run --package knicksiq-api python tools/release/reviewer_false_acceptance.py \
  --records docs/release-evidence/llm-primary-20261021/reviewer/head-units.jsonl \
  --labels docs/release-evidence/llm-primary-20261021/reviewer/labels.json \
  --trials 2 \
  --out docs/release-evidence/llm-primary-20261021/w3-revmeasure/false-acceptance.json \
  --markdown docs/release-evidence/llm-primary-20261021/w3-revmeasure/summary.md
```

The script was exercised end to end with a fake adapter (70 acceptance observations,
provider metadata captured, Wilson and summary written) without any provider call. The live
run is the only missing step.
