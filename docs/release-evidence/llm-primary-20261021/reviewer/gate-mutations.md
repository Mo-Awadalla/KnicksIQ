# Deterministic number gate: offline mutations

`tools/release/analyst_gate_mutations.py` runs the gate alone, with no model calls, over the
correct labeled units in `head-units.jsonl`. Unlike the live replay in `mutations.json`, it
keeps every mutation the gate accepts.

The live replay's head 0/64 is a selection-biased deterministic regression result, not a
reviewer false-acceptance rate. `mutation_candidates` keeps only text swaps the gate already
rejects, and `head_trial` returns `deterministic_rejected` or `structure_rejected` before
calling the reviewer (`tools/release/analyst_review_replay.py:133-152`). All 64 head
observations ended there: 32 `deterministic_rejected` text swaps and 32
`structure_rejected` claim-value changes. The model reviewer was never called on a wrong
number, so its false-acceptance rate is unmeasured.

## Percent ratio (first fix)

The recorded units contain no ratio claims. Each unit therefore gets a sibling claim with
value 0.10, and the answer gains one sentence stating a percentage of it.

| Mutation | Before (`b3fe04a`) | After |
| --- | ---: | ---: |
| Wrong percentage of a 0.10 ratio (11%, 15%, 50%), accepted | 39/39 | 1/39 |
| Right percentage (10%), accepted | 13/13 | 13/13 |
| Stated number moved 1 to 13 display units, accepted | 0/249 | 0/249 |

Cause: the percent branch compared against `tolerance * 100`, but the tolerance is already in
displayed units, so "50%" passed against 0.10 (|50 - 10| = 40 <= 50).

## Coincidence and unit-aware matching (second fix)

The remaining escape was `date_range_last_n-004`: "15%" equalled the plain number 15 in that
unit's trusted numbers (the 15-game window). Any wrong number equal to another trusted number
of another metric passed the same way.

Two mutation families were added to the tool. `coincidence_swap` replaces a number written
next to a unit word with another trusted value whose metric has a different unit.
`percent_count` appends a sentence stating a percentage equal to a trusted count of another
unit. Values that appear in the question are skipped, because the gate legitimately treats
question numbers as criteria in date and coverage spans.

The current `labels.json` marks 14 correct units (the earlier 13 predates the
`comparisons-004` label). Base and head both accept all 14, and both accept all 48 recorded
review attempts (`gate-recorded-attempts.json`).

| Mutation | Base (`5b585e6`) accepted | Head accepted |
| --- | ---: | ---: |
| Coincidence swap, other-unit value | 22/22 | 0/22 |
| Percent equal to a trusted count | 14/14 | 0/14 |
| Wrong percentage of the 0.10 ratio | 1/39 | 0/39 |
| Right percentage of the 0.10 ratio (control) | 13/13 | 13/13 |
| Stated number moved 1 to 13 display units | 0/249 | 0/249 |
| Correct answer unmodified (control) | 14/14 | 14/14 |
| All wrong mutations | 37/324 | 0/324 |

Cause and fix: matching used a flat value set, so any trusted number explained any token.
The gate now parses trusted numbers into sources that carry a unit. A percent token must match
a percent source: a ratio claim times 100, a claim whose unit is percent, or a number written
with a percent sign in a claim statement or receipt. A token written next to points, games,
wins, losses, rebounds or assists must match a source of the same unit, with wins and losses
counted as games because "lost 32 games" states a losses value. Untagged numbers keep value
matching; the model reviewer still judges those, and the tail of a hyphenated compound
("2025-26", "112-98") takes no unit.

Files: `gate-mutations-before.json`, `gate-mutations-after.json`,
`gate-mutations-coincidence-before.json`, `gate-mutations-coincidence-after.json`,
`gate-recorded-attempts.json`.
