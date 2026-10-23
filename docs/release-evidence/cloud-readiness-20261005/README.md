# Cloud release-readiness verification, October 5

**Not release-ready; no launch approval or production deployment.**

This follow-up begins at merge commit
`98060edaac9a3646ecf88573801b705c6a1d0618`, whose committed tree is identical to
PR #6 head `4446758bc21feecbaf199fb1526665c4a6f1db30`. The owner merged PR #6
before this verification began. New changes belong to a separate follow-up PR.

## Accounting hardening

The verification journal now enforces an unconditional **$6 aggregate ceiling**
across stages, inherited settled/failed exposure and current pending reservations.
The historical spending-direction override cannot disable this ceiling. Atomic
reservation, unknown-cost retention, exclusive lineage, fixed request limits and
the independent **$2 monthly application/provider safeguard** remain in force.
A maximum authorization is not proof of available credit or monthly headroom.
Ordinary provider-cost ingestion now rejects coerced strings, booleans, negative or
nonfinite values and out-of-range integers. Unknown costs retain their reservation
instead of releasing uncertain exposure. No inference request was sent and no
provider charge was incurred in this work.

## Coordinated restoration hardening

Before any promotion write, the coordinator now reads the captured API and web
deployment IDs and requires their exact full commit identities. After rollback,
it verifies both the returned deployment ID and the captured prior commit.
Missing identity proof fails before promotion; a wrong restoration remains a
reported failure while restoration of other components continues.

Twenty-six focused synthetic scenarios cover coordinated API/web/data/search reversal,
uncertain mutations, false-success identity mismatches and restoration failures.
They establish coordinator behavior only, not an actual staged rollback rehearsal.

## Verification scope

The published fixture is synthetic, with its own release identity and checksum.
It is not the approved archive or frozen evaluation contract. Local synthetic
checks are implementation regressions; they cannot certify original answer
quality, source correctness, dense retrieval, paid load or launch readiness.

The first complete Redis-enabled backend run passed **776 tests with no skips**.
This is intermediate working-tree evidence, not final-candidate certification.
Local lint/format and full-dependency Pyright passed. Exact PostgreSQL 16.9 CI
migration sequences passed: empty upgrade/downgrade/upgrade, six loader/idempotency
tests and populated pre-Alembic upgrade with retained legacy data. PostgreSQL was
built from verified official source and run only in a disposable local cluster.

Frontend lint, formatting and TypeScript/Vite build passed. A supplemental
non-DOM subset passed 14 tests. Browser execution was blocked before assertions:
the pinned Chromium download returned HTML, while installed Chromium failed at
socket creation with EPERM, including a reviewed retry. These are **not browser
passes**. Original browser assertions and routing controls were unchanged.

Raw synthetic logs, JUnit, configuration, source checksums and intermediate
patches are retained privately under the cloud-readiness artifact directory.
Final exact-commit checks and hosted CI must be bound in the final release record.

The unchanged original stress script also ran against the synthetic archive:
ten concurrent readers for 30 seconds, ten distinct analyst questions and the
61-second cooldown. It recorded archive p95 17.3 ms and analyst p95 1,362.4 ms,
but one factual-response assertion failed, so its result remains **failed**.
The synthetic fixture contains 101 home games and no road games. The unchanged
road-wins question correctly declined to treat missing scope as proof of zero,
so it cannot satisfy this workload’s factual-answer assertion. Neither the
fixture nor the workload was changed to manufacture a pass.
Synthetic owned-process restart and Redis-loss recovery passed 25 checks,
including exact committed replay, retained nonzero accounting, missing-ledger
admission denial and conservative reconciliation.
Neither finding proves original-archive live load or staged recovery.

## Proposed provider admission

[Proposed admission](proposed-admission.json) records a public-metadata-compatible
candidate: the same DeepSeek V4.1 Flash model on `atlas-cloud/fp8`. It is a proposal,
not an activated configuration. The original `morph/fp8` endpoint still reports
status `-2`; the guard correctly rejects it. AtlasCloud reported status `0`, FP8,
required parameters and no pricing discount at observation time. Pricing and
health must be reverified immediately before use.

No single constant was changed to bypass the historical admission. New runtime
identities, exact source/gold bytes, authorized existing credentials, complete
accounting and actual byte-based request bounds must be rebound before inference.
The $6 ceiling does not lift the separate $2 monthly safeguard. Public metadata
cannot prove that the entire workload fits either remaining allowance or meets
latency/quality targets.

## Remaining release gates

- Materialize and verify the approved archive, report/source proofs, frozen
  120-case gold, separate owner approval, original 50 semantic targets and complete
  private accounting lineage
- Admit the exact candidate, model/provider route and isolated runtime; verify
  all four immutable physical search collections, payloads, filters and indexes
- Run the original 120 primary and separate 120 shadow cases, preserving every
  numeric/entity, citation, refusal, Recall@5 and output-bound review requirement
- Complete the original concurrent-user load and actual staged recovery scenarios
- Establish a current rollback snapshot and rehearse coordinated restoration of
  API, web, data version and complete search-alias mapping
- Pass final exact-candidate CI/security and browser checks, then obtain explicit
  owner launch approval bound to the complete release-record hash before deployment

Neither simulated success, historical reports, source comments nor a hand-written
passing record may replace these proofs. The existing readiness validator remains
fail-closed. Private approved data and captured answers must not be published as
public CI artifacts.
