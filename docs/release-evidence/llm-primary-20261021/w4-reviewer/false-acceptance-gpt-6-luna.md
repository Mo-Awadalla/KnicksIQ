# Reviewer false acceptance, live

Measured 2026-10-22T14:48:16+00:00 against the real provider, model `gpt-6-luna`, 2 trials per case. Reviewer calls: 64; cost: $0.0198.

## Per class

| class | cases | trials | accepted | accept rate | Wilson 95% | cost USD | providers |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| number_swapped_other_metric | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0016 | None:6 |
| wrong_subject | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0019 | None:6 |
| wrong_phase_or_window | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0017 | None:6 |
| wins_losses_swapped | 3 | 6 | 4 | 0.667 | [0.300, 0.903] | 0.0019 | None:6 |
| per_game_total_confusion | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0018 | None:6 |
| unsupported_causal_or_ranking | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0024 | None:6 |
| coincident_percent | 3 | 0 | N/A | N/A (gate-blocked) | N/A | 0.0000 | none |

Controls (unmutated correct answers): 25/28 accepted, rate 0.893, Wilson [0.728, 0.963], cost $0.0084.

Deterministic gate: 3 of 21 wrong-answer cases were rejected before the reviewer and are excluded from the rates; 0 of 14 controls were rejected. Reviewer output cap: 3000 tokens.

## Worst accepted examples

- `record_swap_season` (wins_losses_swapped, None): In the available 2025-26 archive, the Knicks went 32-69 across 101 games.
- `record_swap_last_five` (wins_losses_swapped, None): Over their last 5 archived games, the Knicks went 1-4.
- `record_swap_january` (wins_losses_swapped, None): From January 1 through January 31, the Knicks went 8-7 across 15 archived games, scoring 1,652 total points.

