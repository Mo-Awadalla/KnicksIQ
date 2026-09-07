# Offline report verification

Run `python tools/report_audit/audit.py release-artifacts/2025-26/release-candidate.json --output docs/release-evidence/report-audit-20260904` from the repository root. Exit 1 means unresolved report checks; it is an intended release block, not a tool crash.

The tool reads the input without changing it, imports no run detector or report generator, and checks all report hashes, exact score summaries and the three displayed player lines against canonical archive rows. It verifies run points by subtracting cumulative scores at event boundaries. Cached non-scoring 0-0 rows represent missing scores and are carried forward. A nonzero backward score correction blocks certification. The boundary rule is explicit and conservative: the first scoring event at the starting clock is included, as are all events at the ending clock. Clock-only ranges that cannot be reconciled uniquely remain unresolved. This cannot prove which same-clock free throw the original detector selected; original sequence-level detector evidence would be needed to narrow that ambiguity.

`audit.json` binds the exact input file, unchanged canonical basketball collections, report content, review policy and repair proposal with SHA-256 hashes. `audit.md` is generated from it. `report-repairs.json` is a report-only proposal, **not a release bundle**. Only reports passing every check are included and every proposed report is unreviewed. Neither legacy approvals nor `reviewed=true` grants approval under the replacement policy. The owner must approve the corrected template, exceptions and final hash-bound summary after every report check passes. The currently active deployed archive must be independently pinned before any proposal can become a release.

The September 4 audit checked all 101 local reports. All 101 hashes, 101 score summaries and 303 player lines matched. Forty reports have run countdown clocks that contradict their single-quarter descriptions. Every report has at least one unresolved run check, so the repair proposal is empty. For example, game 0022500003 claims NYK 17–3 from Q2 04:30 to 01:51; canonical inclusive endpoints, sequences 170–206, give 16–3. Its CLE 10–0 interval at sequences 132–166 gives 14–2. These discrepancies are recorded with observed sequence ranges for investigation; they are not silently repaired using the original detector's arithmetic.

Tests: `uv run pytest tools/report_audit/test_audit.py -q`.

## Independently reconstructed reports

The September 7 repair uses a separate selector and explicit event sequences to remove the
old clock-boundary ambiguity. Run:

```sh
python3 tools/report_audit/repair.py release-artifacts/2025-26/release-candidate.json \
  --output docs/release-evidence/report-audit-20260907 \
  --candidate release-artifacts/2025-26/release-corrected-unreviewed.json
python3 tools/report_audit/audit.py release-artifacts/2025-26/release-corrected-unreviewed.json \
  --output /tmp/knicksiq-report-independent-verification
uv run pytest tools/report_audit -q
```

`repair.py` enumerates same-period intervals of at most three minutes, grouping all events
at each clock so a free-throw sequence cannot be partly selected. It selects favorable
NYK/opponent scoreboard changes with a fixed, recorded tie-break. It does not import the
application run detector or use the old claimed points. The independently implemented
`verify_exact_run` resolves the named event boundaries against the original rows and checks
scoreboard subtraction, clocks and intervening score corrections without calling the selector.
The descriptions say "Selected scoring interval" and carry their inclusive sequence ranges;
the legacy field names do not establish causal turning points or unrestricted best/worst runs.

All 101 corrected reports pass the separate auditor, including 303 player lines and 303
scoring interval claims. One canonical correction remains untouched: game `0022500125`,
sequence 198, Q2 01:39 changes the away scoreboard from 66 to 65. No selected interval
crosses it. Every replaced claim and this exception are recorded in `audit.json`.

The report-only proposal, its full assembled candidate, and input canonical data are hashed.
The canonical basketball collections remain unchanged. All repaired reports have
`reviewed=false`, and approval maps are empty. Passing factual verification is separate from
owner review of the template, exception and final summary, or verification of active production
identity. This command cannot approve, activate or deploy the candidate.
