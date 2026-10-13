# Release gate handoff (updated 2026-10-12/13)

**Verdict: BLOCKED pending fresh live qualification and remaining release evidence.**
The `exact_statistics-001` application defect is fixed locally and verified without paid calls.
No production change or deployment has been made. The previous readiness result had 18 failures;
that result is historical and does not certify this candidate.

## Latest local fix

An explicit, resolved team-record question now runs the existing `get_team_stats` calculation
before the first model request, unless the exact requested record is already available.
The existing validator still requires both canonical wins and losses. Player and ambiguous
scopes retain their guards. Tool counters, deadlines, budgets, and review requirements are unchanged.

The socket HTTP regression was written before the fix and reproduced the rejected frozen wording,
"What was the Knicks record this season?" It now passes all 13 cases against the approved archive,
including 69 wins and 32 losses over the exact 101-game population. Tests also cover omitted counts,
regular season, playoffs, January, Boston, last ten games, unavailable seasons, player ambiguity,
and Redis replay without additional provider calls. The final affected suite passes all 199 checks.
Planning-call fixtures were updated to preserve budget-exhaustion and invalid-tool coverage.

Current branch: `codex/semantic-release-candidate-20261008`.
The exact source commit, image IDs, final check results, graph update, and artifact hashes are recorded
in the local `evidence/release-20261013/record-regression/verification.json` checkpoint.
Failure modes and test scope: [record availability regression](release-evidence/implementation-20261001/record-availability-failure-modes.md).
The tests use scripted providers; they do not establish live model quality or release eligibility.

## Next run

Preserve successor385b and all its evidence. Its process was killed while paused after rejecting
case 001, so it must not resume. The local successor audit records 398 counted calls, 195,801,300 nUSD
reserved/spent, no newly pending calls, and unchanged historical unknown tickets and four holds.
The read-only monthly observation at 2026-10-13 03:28:15 UTC was 1.251197556 USD, exactly the prior
floor plus this run's 3,231,294 nUSD settled calls. Re-read it immediately before binding any successor.

A closure must retain the original journal bytes and prove that only the stopped flag and failed
primary-run status changed. Label this abandoned after a rejected case, never clean completion.
The local checkpoint links any verified closure and unsigned successor package. Never invent an
owner signature or reuse the consumed e443218 grant for new code or images.

After a current source/image-bound owner grant, activate only the isolated staging images, run
zero-call admission, then repeat all 14 qualification cases in their fixed order with fresh
independent review. Stop through the bound semantic-stop mechanism on the first failure.
Only passing qualification permits the full primary/shadow/disabled cohorts and remaining gates.
The disabled `single_game_narrative-011`, saved 5,349 ms analyst p95 versus the 4,000 ms limit, and
missing ranked retrieval traces remain open. Production launch still needs its own approval.

## Prior source and live run (preserved context)

### Previous source
- Branch `codex/semantic-release-candidate-20261008`, HEAD `e443218a00193ab932e3a3e13cd815ff8b3a125e`.
- `e443218`: `AnalystLoop` runs `get_player_stats` before the model for an explicit, resolved-player average and rejects answers that omit the available average (`_player_average_requested`, `player_average` required group). Fixes the live `exact_statistics-016` failure (model said Towns' rebounding average was unavailable; backend had 1090/94).
- Regression: `test_available_player_average_cannot_be_declared_unavailable_http` (4 cases, failed before / pass after). 139 tests pass across loop-review, narrative, payload, player-intelligence and analyst-contract suites.
- Images built from the commit (CI base-image digests): API `sha256:6dea954ac397d162e20937b7a8bd9e959fe45152ba9c393f7f1410b4bf42c9b1`, web `sha256:90723af7d6dc66201582e3c0f079020684cc9e4ee870da2f7a1489621688b913`.

### Previous live qualification result (successor385b, route inference-net/fp8)
Approved by independent review, all `llm_validated`: `exact_statistics-009`, `010`, `011`, `016`, `date_range_last_n-008`.

**Rejected: `exact_statistics-001`** ("What is the Knicks record?"; frozen 69-32, 101 games). Model returned a clarification ("which Knicks team and season type") with no tool call, no facts, no citations (writer wire 397 chose `answer_from_available_evidence`, `claims: []`). Same class as 016: premature inability. Not observed: 002, 004, 013, 015, 017, 018, 021, 025.

The controller was paused at the case-001 review (no paid calls during pause) and killed by hand; no approval was written for 001. Its goal journal is therefore not a clean stop. A new candidate needs a new exclusive successor package; never resume this journal.

### Previous accounting (inherit all of it)
- 398 counted requests, about 195,801,300 nUSD reserved/spent (385 inherited + 13 new in this run).
- Unknown tickets 26/28/62 and their bounds, the four identified holds, and every stage cap are unchanged: primary 720/$0.50, shadow 48/$0.50, load 66/$0.66, smoke 9/$0.10; task $6, monthly $2.
- The monthly floor must be re-read from the live Redis ledger (`ai-budget:2026-10`, db 14) before drafting any new grant. The first signed grant used a stale floor and failed admission.

### Previous local evidence (git-excluded, under `evidence/release-20261008/`)
- Package: `gate-e443218a…/live/successor385b/` (signed grant, manifest, controller log `controller-execute.log`, `runs/original120-action-schema/` with the five approvals and the `…001-REJECTED.json`).
- Earlier packages: `successor385/` (stale floor, admission failed), `gate-b5733d28…/live/successor377-inference-net/` (b573 predecessor journal, now chmod 0400, sha `dcf77c45…`).
- Staging API/web containers are still running from the e443218 images.
