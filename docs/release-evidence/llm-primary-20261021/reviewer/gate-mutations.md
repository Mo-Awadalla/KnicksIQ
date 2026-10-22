# Deterministic number gate: offline mutations

`tools/release/analyst_gate_mutations.py` runs the gate alone, with no model calls, over the 13
correct recorded units in `head-units.jsonl`. Unlike the live replay in `mutations.json`, it keeps
every mutation the gate accepts. The live replay skipped those candidates, so its 0/64 measured
the model reviewer behind the gate, not the gate itself.

The recorded units contain no ratio claims. Each unit therefore gets a sibling claim with value
0.10, and the answer gains one sentence stating a percentage of it.

| Mutation | Before (`b3fe04a`) | After |
| --- | ---: | ---: |
| Wrong percentage of a 0.10 ratio (11%, 15%, 50%), accepted | 39/39 | 1/39 |
| Right percentage (10%), accepted | 13/13 | 13/13 |
| Stated number moved 1 to 13 display units, accepted | 0/249 | 0/249 |

Cause: the percent branch compared against `tolerance * 100`, but the tolerance is already in
displayed units, so "50%" passed against 0.10 (|50 - 10| = 40 <= 50).

The one remaining acceptance is `date_range_last_n-004`: "15%" equals the plain number 15, which
that unit's claims or receipts already contain. The gate matches values, not units, so a wrong
number that coincides with any trusted number passes to the model reviewer. That limit is open.

Files: `gate-mutations-before.json`, `gate-mutations-after.json`.
