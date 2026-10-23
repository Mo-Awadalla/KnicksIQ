# Reviewer false acceptance, live

Measured 2026-10-22T15:07:49+00:00 against the real provider, model `gpt-6-luna`, 2 trials per case. Reviewer calls: 58; cost: $0.0180.

## Per class

| class | cases | trials | accepted | accept rate | Wilson 95% | cost USD | providers |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| number_swapped_other_metric | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0016 | None:6 |
| wrong_subject | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0020 | None:6 |
| wrong_phase_or_window | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0016 | None:6 |
| wins_losses_swapped | 3 | 0 | N/A | N/A (gate-blocked) | N/A | 0.0000 | none |
| per_game_total_confusion | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0018 | None:6 |
| unsupported_causal_or_ranking | 3 | 6 | 0 | 0.000 | [0.000, 0.390] | 0.0024 | None:6 |
| coincident_percent | 3 | 0 | N/A | N/A (gate-blocked) | N/A | 0.0000 | none |

Controls (unmutated correct answers): 26/28 accepted, rate 0.929, Wilson [0.773, 0.980], cost $0.0084.

Deterministic gate: 6 of 21 wrong-answer cases were rejected before the reviewer and are excluded from the rates; 0 of 14 controls were rejected. Reviewer output cap: 3000 tokens.

## Worst accepted examples

None.

