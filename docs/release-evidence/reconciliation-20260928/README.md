# Narrow release reconciliation — BLOCKED

Candidate: **91ada687ec6e6a3c4bb2ac2a561e91f6c8ea8cc3** on local branch
`codex/release-reconciliation-20260928`, parent `e003db2d7f179c8d490d90155f260ec0eeb31620`.
Only the evidence-loop sampling fix, its HTTP regression and the launch-policy
proposal are included. The current working branch and pre-existing local
release evidence were not replaced. Nothing was pushed. `source-identity.json`
verifies 3,900 candidate file blobs, including symlinks, against the files used
for local checks. Prior merge CI 36472142614 remains evidence for e003db2 only.
The preliminary local 2274d1e candidate was superseded for test formatting.

## Behavior and policy

Shadow sampling now gates model admission in the enabled evidence loop using
the existing request-ID sampler. Unsampled turns still produce factual answers,
citations and committed state. Replay returns before sampling/model admission.
Primary mode remains unsampled; reservation, evidence validation, fallback and
session implementations are unchanged. The log records sample membership.

[Proposed policy](../../release-policy-proposal.md): retain pre-promotion
shadow/0.1 as a required verification stage; record llm_primary separately as
the intended final serving mode. Require both stages, all existing quality
gates and final record-hash authorization. The existing validator is unchanged
and still blocks a primary-mode release record. Owner policy approval and a
subsequent validator implementation/CI candidate are required before this can
become the effective policy. Production configuration was not changed.

## Completed candidate checks

- HTTP sampling regression: 7 cases; rate 0, rate 1, sampled/unsampled 0.1,
  primary at rate 0, missing budget, malformed provider output; every case
  checks factual citations, replay with a different request ID and changed-
  payload conflict. Red failure was captured before implementation.
- Backend: **407 passed**, no Redis skips; PostgreSQL loader/idempotency:
  **6 passed**. Ruff, format and Pyright passed. Empty and legacy migration,
  expand-only rollback, and retained legacy records passed locally. Hosted
  CI's PostgreSQL 16 / Ubuntu environment is still a separate requirement;
  loader/legacy rehearsals here used isolated PostgreSQL 18.
- Frontend: lint/format, **47 browser tests**, **38 E2E tests** passed, including
  keyboard, responsive layouts and accessibility. Repeatable HTML report:
  [browser-report/index.html](browser-report/index.html).
- Exact candidate Git-archive API/web image builds passed; Trivy found zero
  critical fixable vulnerabilities in both. Gitleaks candidate-diff passed.
  Whole-archive scan retained one finding: an old Render deployment ID in
  `rollback.api_deployment`, classified as an identifier rather than a secret.
  It was not suppressed or used to claim a clean whole-tree scanner exit.
- Approved bundle hash and existing template/exception/report approval hashes
  match. Fresh audit: **101/101 reports, 303 player lines, zero unresolved**.
- Retained full backup hash verified and restored locally. Candidate load and
  repeated load passed; 3,867 restored source rows and 4,160 label references
  were field/hash checked. Old release retained, locally reactivated, and
  candidate reactivated; original report hashes preserved. The old bundle
  itself lacks today's report approvals and is not a valid reload mechanism;
  the retained database, not a bypassed loader, was used for rollback.
- Local real MiniLM index build: **101 games, 2,950 box rows, 15,864 possessions,
  101 reports**. Vector dimensions, release identity, relevant metadata filters,
  wrong-release exclusion, UUID/source identity and all report title/summary
  payloads verified. Embedded Qdrant does not enforce server payload indexes;
  this is not hosted/cloud-inference verification.
- Production-profile local factual fallback in both modes and local receipt
  recipe checks passed. Ten-client local concurrency 10: archive p95 **124 ms**,
  analyst p95 **1,379 ms**, **0% errors**. Single-client rehearsal hit existing
  rate limits (43% rejected); preserved separately, with no limits raised.
  These results are not full live-provider primary or hosted load evidence.
- Read-only production checks confirmed schema 0005, active July release,
  unchanged API/web rollback deployments and four retained old collections.
  **All four candidate remote collections are absent.** Header GETs returned
  HTTP errors; served-header verification is not claimed complete.
- Graphify AST update completed locally without model calls.

## Evaluation decisions

[Exact proposed scoring protocol](evaluation-contract.md),
[all 120 proposed expectations](expectation-review.json), and
[50 semantic target decisions](semantic-decisions.md) are local review artifacts.
Proposed outcomes remain 58 answer / 53 clarify / 9 refuse. Clarification and
refusal are distinct; the old substring scorer is not suitable. Local SQL,
receipt-recipe and vector-document mappings now exist. Source reference matches
are not answer/citation correctness or semantic relevance.

Owner decision: **Keep unresolved cases blocking release.** No final label
approval requested, no approved-expectation freeze fabricated, no final
120-case evaluation run. All 50 original semantic cases stay in the denominator.
Document targets still need adjudication, and the final runner must capture
actual ranked retrieval traces; current evidence-loop responses do not export
the legacy trace fields. Missing retrieval cannot be filled with a separate
search and claimed as the analyst's behavior. No thresholds/cases were changed.

## Provider and paid evaluations

The 3-schema/1-synthetic-turn compatibility smoke is authorized for at most
9 completion requests and $0.10, counting all nested calls and retries, with
$2 monthly cutoff unchanged. **Stopped at preflight: real monthly Redis ledger
unreachable. Zero compatibility completion requests, $0 compatibility spend.**
Pricing/cost bounds were not certified after that stop; no ledger was reset.
This is blocked, not a smoke pass or quality evidence.

Separate proposals, not authorizations:
- Service-disabled 120-case evaluation: **0 paid requests, $0**.
- Service-enabled primary 120-case evaluation: up to **720 total completion
  requests / $0.50 aggregate**, no extra transport retries, local embeddings.
- Distinct pre-promotion shadow evaluation: up to **720 requests / $0.50** as
  an absolute ceiling, reduced to six times the actual selected turn count
  before requesting execution approval.

Both paid proposals remain **unverified and not execution-ready** until a
conservative token/price/reasoning bound is proved, counted wrappers enforce
the aggregate caps, real ledger availability is restored and the unchanged
monthly allowance suffices. Stop rather than continue or exceed a cap. Any
cloud embedding cost also requires an explicit verified bound. The smoke does
not replace either 120-case quality run or the shadow stage.

## Preserved failures and limits

An initial frontend run used a production API origin while fixture routes
expected `/api`. It was stopped after failures, retained as
`frontend-e2e-origin-mismatch.txt`, and replaced by the passing local `/api`
fixture run. That interrupted run may have reached the public API; network
traces were not captured, so zero incidental traffic/provider cost is **not
asserted** for it. It is not valid verification. No intentional production load,
failure injection, deployment, remote staging, alias promotion, activation or
evidence publication was performed. Compatibility-smoke accounting above is
specific to that preflight and is not a claim about unobserved browser traffic.

## Remaining release blockers / authorization order

1. Policy proposal approval, then explicit gate implementation and a new tested
   candidate if code changes. Existing gate is still in force.
2. Semantic target adjudication, final scoring review, actual trace capture,
   hash-bound expectation approval/freeze; then both 120-case evaluations and
   distinct shadow verification. Paid runs need separate bounded authorization.
3. Reachable, reconciled real monthly ledger and verifiable provider price bound;
   only then the already-authorized synthetic smoke within its original caps.
4. **Required hosted CI for this exact candidate, including CodeQL, is not run.**
   Triggering it requires a push/remote event; no remote write is authorized.
   Local commands, image scans and historical CI cannot be called a new hosted run.
5. Staging-write authorization naming exact destinations/resources → create
   candidate resources → staged schema/index/dependency/rollback verification
   → completed release record → final promotion authorization bound to its hash.
   Candidate remote verification cannot pass while the collections are absent.
6. Hosted/live-mode readiness and post-promotion served acceptance remain distinct
   from local rehearsals. Current HTTP-header checks remain unavailable.

The new `release-record.json` here is a **blocked draft**, not a completed release
or authorization request. Historical records are untouched. Its hash is only
an integrity reference; final production approval must bind a later completed
record. Approved bundle and all production-derived artifacts remain local.
Disposable local databases have been stopped; the PG18 container/data remain
available for reproducible continuation (`docker start knicksiq-reconciliation-pg18`).
