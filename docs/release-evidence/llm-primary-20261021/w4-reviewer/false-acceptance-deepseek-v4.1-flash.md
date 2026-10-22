# Reviewer false acceptance, live

Measured 2026-10-22T14:54:04+00:00 against the real provider, model `deepseek-v4.1-flash`, 2 trials per case. Reviewer calls: 64; cost: $0.0596.

## Per class

| class | cases | trials | accepted | accept rate | Wilson 95% | cost USD | providers |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| number_swapped_other_metric | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0050 | None:6 |
| wrong_subject | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0059 | None:6 |
| wrong_phase_or_window | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0050 | None:6 |
| wins_losses_swapped | 3 | 6 | 2 | 0.333 | [0.097, 0.700] | 0.0060 | None:6 |
| per_game_total_confusion | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0058 | None:6 |
| unsupported_causal_or_ranking | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0070 | None:6 |
| coincident_percent | 3 | 0 | N/A | N/A (gate-blocked) | N/A | 0.0000 | none |

Controls (unmutated correct answers): 28/28 accepted, rate 1.000, Wilson [0.879, 1.000], cost $0.0250.

Deterministic gate: 3 of 21 wrong-answer cases were rejected before the reviewer and are excluded from the rates; 0 of 14 controls were rejected. Reviewer output cap: 3000 tokens.

## Worst accepted examples

- `record_swap_january` (wins_losses_swapped, None): From January 1 through January 31, the Knicks went 8-7 across 15 archived games, scoring 1,652 total points.

