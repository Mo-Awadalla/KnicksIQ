# Release gate handoff (paused 2026-10-12/13)

**Verdict: BLOCKED.** No production change, no deployment. Readiness validator: `eligible=false` (18 failures).

## Code state
- Branch `codex/semantic-release-candidate-20261008`, HEAD `e443218a00193ab932e3a3e13cd815ff8b3a125e`.
- `e443218`: `AnalystLoop` runs `get_player_stats` before the model for an explicit, resolved-player average and rejects answers that omit the available average (`_player_average_requested`, `player_average` required group). Fixes the live `exact_statistics-016` failure (model said Towns' rebounding average was unavailable; backend had 1090/94).
- Regression: `test_available_player_average_cannot_be_declared_unavailable_http` (4 cases, failed before / pass after). 139 tests pass across loop-review, narrative, payload, player-intelligence and analyst-contract suites.
- Images built from the commit (CI base-image digests): API `sha256:6dea954ac397d162e20937b7a8bd9e959fe45152ba9c393f7f1410b4bf42c9b1`, web `sha256:90723af7d6dc66201582e3c0f079020684cc9e4ee870da2f7a1489621688b913`.

## Live qualification result (successor385b, route inference-net/fp8)
Approved by independent review, all `llm_validated`: `exact_statistics-009`, `010`, `011`, `016`, `date_range_last_n-008`.

**Rejected: `exact_statistics-001`** ("What is the Knicks record?"; frozen 69-32, 101 games). Model returned a clarification ("which Knicks team and season type") with no tool call, no facts, no citations (writer wire 397 chose `answer_from_available_evidence`, `claims: []`). Same class as 016: premature inability. Not observed: 002, 004, 013, 015, 017, 018, 021, 025.

The controller was paused at the case-001 review (no paid calls during pause) and killed by hand; no approval was written for 001. Its goal journal is therefore not a clean stop. A new candidate needs a new exclusive successor package; never resume this journal.

## Accounting (inherit all of it)
- 398 counted requests, about 195,801,300 nUSD reserved/spent (385 inherited + 13 new in this run).
- Unknown tickets 26/28/62 and their bounds, the four identified holds, and every stage cap are unchanged: primary 720/$0.50, shadow 48/$0.50, load 66/$0.66, smoke 9/$0.10; task $6, monthly $2.
- The monthly floor must be re-read from the live Redis ledger (`ai-budget:2026-10`, db 14) before drafting any new grant. The first signed grant used a stale floor and failed admission.

## Local-only evidence (git-excluded, under `evidence/release-20261008/`)
- Package: `gate-e443218a…/live/successor385b/` (signed grant, manifest, controller log `controller-execute.log`, `runs/original120-action-schema/` with the five approvals and the `…001-REJECTED.json`).
- Earlier packages: `successor385/` (stale floor, admission failed), `gate-b5733d28…/live/successor377-inference-net/` (b573 predecessor journal, now chmod 0400, sha `dcf77c45…`).
- Staging API/web containers are still running from the e443218 images.

## Next steps
1. Reproduce the 001 failure offline through real HTTP/SQL/Redis with a scripted provider (write the failing test first, per AGENTS.md): an explicit Knicks-record question must run the existing record/team calculation before the model can clarify, and the answer must carry both wins and losses claims. Check scope resolution first: the clarification is the model's, but find why no record claim was prepared.
2. Fix at the source; rerun the affected suites; `graphify update .` (takes ~6 min; run with no deadline).
3. Commit; build both images with the CI build contexts; build a new package from the **current** journal (this run's `goal.sqlite`, counts, exposure and settled calls) and re-read the Redis floor.
4. Owner signs a new grant (`bind_signed_grant.py`); activate; `--prepare-only`; run all 14 cases from the start (the order is fixed and a new commit invalidates earlier approvals); stop on first failure.
5. Only after all 14 pass fresh independent review: full primary 120, shadow, disabled 120/50, load, recovery/migration/rollback, hosted CI, browser smoke; then readiness validator and owner approval.
Open evidence failures from earlier gates stand: disabled cohort `single_game_narrative-011`, saved load analyst p95 5,349 ms vs 4,000 ms, and missing ranked retrieval traces.
