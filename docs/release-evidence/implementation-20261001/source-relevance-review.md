# Current source relevance review

The original 120-question expectation review and all 50 semantic members are retained. Seven settled target sets remain byte-equivalent in content, including all nine Atlanta games. The new review identifies 38 candidate target sets and leaves five measure-dependent target sets unresolved. These are proposals, with no owner approval or freeze.

Review artifact: `release-artifacts/implementation-20261001/source-relevance-proposal.json`.
SHA256: `e24a016ee325d36e722068ea3f079871bf90a456e34a65e713f2537bab92f180`.

The actual canonical JB identity document is independently relevant to recognizing Jalen Brunson while asking “Which game?” when the immutable context contains no identified game. This establishes no missing game or performance facts. An identified game in the preceding ten messages still permits an answer from canonical rows.

The five approved measure clarifications remain in force. Current word matches and generic result documents do not establish their missing measure-specific retrieval targets. No new metric default, excluded semantic member or manufactured mapping is introduced.

| Case | Question | Missing source support |
| --- | --- | --- |
| single_game_narrative-018 | Describe the Knicks' worst third quarter. | The approved question asks which Q3 measure and scope. The previous fewest-points selection alone cannot define targets for an unspecified worst-quarter measure; the actual ranked rebound descriptions do not support that distinction. |
| turning_points-005 | How did the Knicks erase their largest deficit? | Game result documents do not establish largest observed versus erased deficits or the selected meaning of erased. No measure-specific target population is supported by this current capture. |
| turning_points-007 | What was the most damaging opponent run this season? | The actual ranked running-layup descriptions match a word, but do not define or identify the requested most damaging opponent scoring run over the season. |
| aliases_typos-005 | What was the Knics biggest run? | The actual running-layup descriptions do not establish unanswered-run versus net-window-gain definitions, boundaries or the requested scope. |
| aliases_typos-010 | What was NY's worst collpase? | The current rankings contain generic result/box documents and a selected positive scoring interval. They do not define a lead surrendered versus margin decline or a season-wide worst collapse. |

All 50 case records bind the original question/context, canonical fact digest, actual top-five IDs, captured response hash and independently verified unit receipts where available. A correct clarification or canonical answer does not imply passing retrieval. The tied closest-game stories and Boston runs have canonical fact support; their complete indexed/ranked source mappings still need proof.

Next dependent release steps require supported targets for all 50 cases, complete current receipt mapping, then content-bound owner approval of the full frozen expectations. Guarded counted execution, the three original cohorts, hosted dependency/load/recovery/rollback evidence and final digest-bound launch approval remain open. Production and current staging plans are unchanged.

## Measure-source audit failure modes

The next prerequisite is an offline CLI audit of the complete, explicitly
hash-bound archive, not a new measure default or an evaluation. Its public seam
is a subprocess command with durable JSON/checksum artifacts. The E2E
specification precedes implementation.

- Reject a changed bundle digest, changed content manifest, missing/duplicate
  scheduled games, foreign source rows, invalid score types, and non-final or
  foreign-team populations.
- Keep missing/duplicate period rows, inconsistent period/final totals,
  missing/duplicate/noncontiguous event sequences, decreasing scores,
  simultaneous scoring, wrong-team scoring, oversized scoring increments, and
  final-score mismatches visible. Never drop a game to certify the season.
- Distinguish fewest third-quarter points from worst third-quarter margin;
  preserve every tie and separate regular-season/postseason populations.
  Missing quarter coverage prevents extrema certification for that population.
- Zero-score sentinel rows and quarter boundaries do not fabricate scoring.
- A supplied upstream capture may corroborate a bad row, but cannot repair it
  or establish source approval. Preserve action IDs and both source hashes.
- Refuse existing output paths; reproduce identical audit bytes in fresh paths.
  A blocked source audit must exit nonzero, while retaining its complete report.
- Never access credentials, providers, SQL, Redis, production state, or the
  network. Never create ranked receipts, change targets/contexts, approve gold,
  or claim release readiness.

## October 3 source-integrity findings

`tools/release/audit_measure_sources.py` audits the complete pinned archive.
`tools/release/check_measure_sources.py` exercises its actual subprocess
interface with socket creation denied and retains every result. The 25-case
E2E run passed, including malformed-source controls, blocked exits, identical
repeat outputs, overwrite protection and a deliberately altered upstream
capture. Ruff and scoped Pyright also passed. This changes no runtime behavior.

Private proof is in the main project's ignored
`release-artifacts/source-support-20261003/`: `e2e-final/e2e-result.json`,
`e2e-final/first/measure-source-audit.json`, its `SHA256SUMS`, the retained red
run, and `official-0022500125.json`. No private archive or capture is published.

All 101 games have complete period pairs whose sums agree with the finals.
Fewest Knicks Q3 points selects `0022500835` (11 points, margin -12).
Worst Knicks Q3 margin selects all three tied games `0022500003`,
`0022500125` and `0022500816` (margin -15). These distinct, independently
supported alternatives do not select a default or resolve the question's
missing scope. The report retains every Q3 source row and hash and separates
archive, regular-season and postseason candidates. Indexed/ranked source
mapping and gold approval remain absent.

Only 100 of 101 games pass the raw scoring-sequence audit. In `0022500125`,
event 197 changes MIL/NYK from 52/65 to 55/66 on a Knicks free throw; event 198
then reduces NYK to 65 on a Milwaukee three-pointer; event 199 increases NYK
by four on a three-pointer. The current
[official NBA page](https://www.nba.com/game/nyk-vs-mil-0022500125/play-by-play)
contains the same scoreboards at action numbers 308, 318 and 309 respectively.
The supplied capture corroborates those exact descriptions, clocks, teams and
scores, retaining action IDs and hashes. This is an upstream discrepancy, not
evidence authorizing a repaired archive. The alternate NBA CDN feed returned
access denied, and a direct stats endpoint request timed out.

An exploratory reconstruction from made-shot descriptions and non-MISS free
throws agrees with all 816 period totals and all 2,748 player box-score point
totals. It also exposes a running-points description disagreement at
`event:0022500343:419`. That finding is retained separately in
`reconstruction-feasibility.json`. Aggregate agreement alone cannot establish
every intermediate scoreboard or approve a reconstruction recipe. The audit
therefore keeps the raw scoring discrepancy visible rather than silently
repairing it, dropping the game or certifying season-wide sequence measures.

To repeat the complete E2E proof, choose a fresh output directory:

```sh
/Users/mohamedawadalla/Projects/KnicksIQ/.venv/bin/python \
  tools/release/check_measure_sources.py \
  --bundle /Users/mohamedawadalla/Projects/KnicksIQ/release-artifacts/2025-26/reliability-approved-20260928.json.gz \
  --official-actions /Users/mohamedawadalla/Projects/KnicksIQ/release-artifacts/source-support-20261003/official-0022500125.json \
  --output /private/tmp/knicksiq-measure-source-recheck-NEW
```

The audit alone exits 2 with `BLOCKED_SOURCE_COVERAGE` on this unchanged archive;
the E2E wrapper exits 0 only after proving that blocked result and its negative
controls. This does not close any of the five unresolved measure target sets.
The next source step needs independently supported action-level scoring
provenance or an independently adjudicated derived-source recipe, followed by
actual indexed/ranked mappings. All 120 questions, 50 semantic members, seven
settled target sets, approved clarifications, thresholds and existing budgets
remain unchanged. No completion request, reservation, freeze, merge or launch
occurred.
