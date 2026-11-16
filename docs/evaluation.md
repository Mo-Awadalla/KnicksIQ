# Answer and retrieval evaluation

The immutable primary set contains 120 questions.
Typed expectations describe proposed facts, entities, citations, clarification and refusal.
Release approval requires reviews bound to the exact recorded responses.

Release gates require 100% disposition, numeric, entity, scope and abstention correctness.
They also require no unsupported facts and at least 95% paraphrase and citation correctness.
All 50 original semantic case IDs remain in the primary set and receive behavior scoring.
SQL answers and clarification responses do not receive invented document-retrieval credit.
A separate 20-case narrative benchmark requires at least 95% document Recall@5.
The provider-free primary run must remain correct with its optional services disabled.
The narrative benchmark separately uses real SQL, Qdrant and local embeddings.

Public chat replies contain text and lifecycle status, not citations, analytics or tool traces.
The citation gate reports `inapplicable: public citations retired; owner-approved rubric migration pending`.
It retains its 58-case denominator and no passing value. Release stays blocked pending approval.
The latency ceiling and error threshold remain unchanged.

## What is and is not approved

The immutable `apps/api/app/evaluation/questions.jsonl` contains all 120 original questions.
`docs/release-evidence/reconciliation-20260928/expectation-review.json` proposes their typed
expectations. Its approval is null and it is not frozen.

The recorded label digest matches the 120-row local artifact
`docs/release-evidence/evaluation-label-review-20260907/labels.jsonl`. Digest verification requires
the artifact's content, not a trusted string.

The operator approved route-aware scoring and a separate real retrieval benchmark.
That policy does not approve or freeze either label proposal.
The original 120 questions and 50 semantic case IDs remain unchanged.
No case leaves its denominator because the application clarifies, refuses or fails.
The evaluator never manufactures gold approval or successful provider measurements.

## Chat collection and text checks

Collection posts `POST /chat/turns` with a fresh random `X-Chat-Token` for each case.
Earlier user context messages are real commands in the same conversation. Their replies come
from the candidate, not injected assistant text. Each settled snapshot advances the next revision.
The collector records those actual context turns, the command, final reply text, status, reason,
revision and delta count. It rejects remote candidates, redirects and ambient proxies.
Original assistant context remains label metadata, not fabricated server history.

Numeric gold values and case IDs remain unchanged. Integer presence is exact and decimal
presence respects displayed precision. Expected player names must appear in the reply.
Presence alone does not prove attribution or scope. Bound human reviews judge disposition,
paraphrase, scope and additional assertions. Missing reviews block those measurements.
The public reply does not claim a structured outcome. The reviewer records answer, clarification
or refusal independently. Missing or interrupted replies never become correct abstentions.

Legacy typed-claim arithmetic and mapping checks remain offline factual diagnostics.
They do not establish that a chat reply exposed or used public receipts.
`citation_receipt_correctness` is explicitly inapplicable, not passing private-fact evidence.

## Freeze and approval artifacts

Approval requires content-bound manifests, not `owner_approved` booleans or a note.
The `evaluation-freeze-v1` manifest binds the question bytes, canonical expectation content,
verified label digest, 120-case count, original 50 semantic case IDs, protocol and timestamp.
The `evaluation-approval-v1` manifest binds that freeze digest and label digest to a named
approver, approval timestamp and `approved: true`.

Missing or stale manifests block with `labels_not_frozen`, `labels_freeze_unverified` or
`labels_approval_unverified`. Changing covered content invalidates the freeze and bound reviews.
The evaluator never creates approval. The current proposals carry none.

## Ranked traces come from the retrieval boundary

`app/services/archive_retrieval.py` emits a `RetrievalTrace` at the fusion boundary: the lexical
ranking, the dense ranking, the fused candidate ordering before the caller's final limit, and the
selection the caller actually emitted (whatever its length). Each record carries the request id
and release it belongs to; a trace without both is rejected. The separate narrative collector obtains these private traces directly from `AnalystTools`.
They never appear in public chat replies.

Each stage has its own Recall@5 and Recall@20 diagnostic in the separate narrative report.
The mandatory `narrative_recall_at_5` gate uses the first five entries actually emitted.
The scorer preserves ordering and never repairs ranks or re-queries to improve a score.
Missing cases, duplicate cases, malformed ranks and incomplete collection seals block release.

Narrative relevance uses exact document identities.
Collection, game, point ID and payload hash must match the frozen corpus mapping.
A different possession from the same game receives no relevance credit.
Opaque sequence IDs remain strings and never stand in for canonical game IDs.
The legacy game-collapsing retrieval mapper is removed.

The source-first narrative proposal contains 20 explicit questions and 21 relevant documents.
Its targets were recorded before any ranked query.
The retrieval code parses an explicit quarter and clock from the question itself.
Lexical and dense search apply the same event constraint before ranking.
Neither search receives gold document IDs.

The profile binds the actual index embedding revision, query embedding revision,
retrieval settings and implementation hash.
Collection rejects a changed implementation or different embedding weights.
`python -m app.evaluation.cli narrative` collects with `--collect` or scores sealed observations.
It takes the primary questions, expectations, SQL mapping, document mapping,
`--narrative-labels`, `--narrative-profile` and `--narrative-observations`.
An optional `--narrative-approval` must match the benchmark identity.
This measurement covers real archive-tool retrieval, not 20 model-authored narrative answers.

## Recorded reviewer decisions

Natural-language assertion judgment requires recorded reviewer decisions.
`evaluation-review-decisions-v2` binds `evaluation_identity_sha256` to the question,
expectation, label, protocol, mapping, document-mapping and narrative-label digests.
Every case includes the delivered disposition, assertion spans, verdicts, evidence and
canonical fact indices where the assertion makes an answer claim.

The loader rejects foreign identities, unknown cases, malformed dispositions and invalid
supported fact references.
An honest wrong-disposition review remains a measurable failure.
An omitted required fact remains a failure without an invented assertion for the omission.
Abstention reviews may record policy assertions without canonical fact indices.
A supported answer review still needs assertions and valid supporting evidence.
The scorer binds every assertion span to the actual response text.
A missing span leaves the case `review_unbound_assertion` and unreviewed.
An `unsupported` assertion fails the unsupported-fact gate.
An `insufficient_evidence` verdict blocks with `assertion_evidence_unresolved`.

Until every one of the 120 responses has a valid review, `disposition_accuracy`,
`clarification_accuracy`, `refusal_accuracy`, `correct_abstention`, `answer_quality` and
`paraphrase_quality` report `blocked` and release stays blocked. The evaluator never writes,
infers or approves a decision.

## Fixed denominators and reporting

Every original case is scored, and every metric states its own denominator and status
(`measured`, `failed`, `blocked` or `inapplicable`) with the cases that failed it:

| Metric | Denominator |
| --- | --- |
| `disposition_accuracy` | 120 |
| `correct_abstention` | 62 (clarify 53 + refuse 9) |
| `clarification_accuracy` | 53 |
| `refusal_accuracy` | 9 |
| `canonical_numeric_correctness`, `canonical_entity_correctness`, `scope_window_denominator_correctness`, `unsupported_additional_fact_rate`, `citation_receipt_correctness`, `paraphrase_quality`, `answer_quality` | 58 answer cases |
| `legacy_semantic_behavior_accuracy` | 50 original semantic cases |
| `narrative_recall_at_5`, `narrative_recall_at_20` | 20 independently labelled narrative cases |

A response missing from the submission is `cases_missing` and its case fails: denominators stay
fixed and the case is never dropped. Duplicate observations and responses for unknown cases are
explicit `duplicate_observation` / `unknown_case_observation` failures.

Every mandatory gate is derived from the recorded failure codes, not from a parallel enumeration:
`no_typed_claim_for_fact`, `release_mismatch`, `evidence_scope_mismatch`, `evidence_unmapped`,
`claim_not_displayed`, `season_mismatch`, `denominator_mismatch` and `scope_not_expressible` fail
their numeric, scope or entity gate, and an observation whose digest, request identity, turn or
case binding does not verify (`verified: false`) contributes no passing measurement at all.

Gates stay blocked while labels lack approval or a verified freeze.
Missing narrative observations or narrative approval also block release.
Missing subjects, citation content, assertion evidence and reviewer decisions block their metrics.
Missing or duplicate cases and model stages under a provider-free profile block release.
An unavailable mandatory measurement adds `gate_blocked:<metric>`.

## Running it

Use an isolated loopback PostgreSQL restore of the approved archive.
Set `LOCAL_DB` to that disposable database URL. Never use a production database.
The mapping command verifies the restore without changing its rows.

```bash
OUT=release-artifacts/production-candidate
uv run --frozen --package knicksiq-api python tools/release/enrich_expectations.py \
  --output-dir "$OUT"
uv run --frozen --package knicksiq-api python tools/release/runtime_mapping.py \
  --dsn "$LOCAL_DB" --output "$OUT/runtime-mapping.json" \
  --report "$OUT/runtime-mapping-verification.json"
uv run --frozen --package knicksiq-api python tools/release/eval_runner.py \
  --db-url "$LOCAL_DB" --mapping "$OUT/runtime-mapping.json" \
  --expectations "$OUT/expectation-review-proposed.json" --output "$OUT/disabled"
```

The enrichment tool adds only independently grounded subject metadata.
It packages the original label bytes beside the proposal.
It does not approve labels, freeze them, change dispositions or decide semantic targets.

The runner owns its API socket, rejects remote databases and redirects, and uses an explicit
environment without inherited `.env` settings or proxies. It stops the child process group
and writes a durable summary, including startup and cleanup failures.
The disabled profile has provider access disabled by its bound environment.
Public deltas do not measure private provider calls; the provider count reports inapplicable.
Use `--documents` only for index identities verified against the same restore.

Collection preserves each immutable question and sends earlier user context as actual chat commands.
Recorded commands, revisions, request IDs and response digests must verify.
The transcript records actual generated context replies, not the historic assistant fixtures.

### Approved service execution

See the [approved service evaluation guide](evaluation-service.md) for operator
approval, exact candidate binding, funding checks, the durable budget ledger, and
signed response proofs. Gold-label approval remains a separate requirement.

## Report shape

`evaluation-report-v3` contains dataset digests and counts, mapping identity and profile evidence.
The profile separates unavailable public provider counts from privately attested attempts, reservations and settlements.
`semantic` records the route-aware policy and the original 50 case IDs.
`narrative` contains the separate document benchmark report and its bound identity.
The report also includes dispositions, metrics, gates, blockers and every original case.
Each case records checks, failures, citation results, review state, integrity and latency.
`release_blocked` remains true when a required measurement is unavailable.


## Failures and blockers

Each case records stable failure codes with the affected fact, reference or token.
The report distinguishes wrong values, units, subjects and populations from missing evidence,
invalid request identity, unsupported assertions and invalid retrieval traces. Read each case's
`failures` and `blockers` before interpreting aggregate metrics.

Missing label approval, freeze, narrative evidence or answer reviews block release.
The retired public-citation gate remains inapplicable and blocks release pending rubric approval.
Model stages in a provider-free profile also block release.
A failed mandatory measurement adds `gate_failed:<metric>`.

The authoritative checks live in `app/evaluation/assertion_checks.py`, `mapping.py`,
`observations.py`, `reviews.py` and `scoring_cases.py`. The report carries the exact codes.
