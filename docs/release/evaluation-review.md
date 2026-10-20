# Local evaluation review interface

This is an internal workflow specification, not approved release labels or evidence.
All 120 original cases, including all 50 original semantic cases, remain required.
Unresolved targets and disposition/fact adjudications block freezing; frozen
expectations still require a separate owner approval bound to the exact
expectation file SHA-256. A context-free clarification must have empty
conversation context and targets, set `context_free_clarification: true`, and
expect `clarify`.

Capture the service-disabled cohort with the existing runner's `--mode disabled`.
Primary and optional shadow collection accept an explicit `CountedRun` dependency.
It installs the counted transport, requires environment verification before the
cohort and payload verification before every provider request, preserves partial
evidence, and stops even if the analyst masks a provider failure with fallback.
The command-line collector has no default live verifier: paid execution remains
blocked until real monthly accounting, current conservative provider bounds,
isolated resource identities and billed dependencies are independently verified.
When shadow is explicitly selected, request IDs and membership are fixed before
calls; its durable journal cap matches six times the actual selected count. The
accounting snapshot is cumulative across attempts; `paid_requests` is the current
attempt's delta.

Reviewers inspect each complete answer, its typed facts and scope, and the actual
receipts. They record contiguous assertion spans covering the entire answer.
Allowed classifications are `factual`, `clarification`, `refusal`, and `nonfactual`.
A factual assertion names `canonical_fact_ids`: the runner's canonical JSON digest
of each applicable frozen fact object. It also names `citation_evidence_ids` that
actually appear in the response citations. The runtime mapping must map each cited
reference to a canonical source supporting the named frozen fact. Every expected
fact must be covered for an answer review to be complete.

For each semantic clarification, `listed_candidate_game_ids` contains every
canonical game ID the answer explicitly presents as a candidate. Reviewers
include incorrect candidates too. The field is stored in the review for the
specific output SHA. Incomplete lists receive partial Recall@k credit; any
non-target candidate makes that case score zero. Clarification cases do not
require ranked search traces because the analyst may clarify before retrieval.
For a context-free clarification, the list and both candidate and returned
search evidence must be empty.

These mechanical checks establish identity and coverage, not semantic correctness.
A shared source reference alone does not prove the wording, numeric claim, entity,
or scope is correct. Those remain explicit reviewer judgments. Nonfactual spans
must not hide factual assertions. Additional facts outside the frozen contract
cannot be certified by inventing fact IDs during output review; retain a failing
or unresolved result and follow the independent expectation-adjudication process.
Do not relabel to match candidate output.

After capture and review, produce a new private metrics file:

```sh
python -m app.evaluation.release_runner /private/expectations.json \
  --approval /private/owner-approval.json --mode disabled \
  --observations /private/observations.json --reviews /private/reviews.json \
  --mapping /private/runtime-mapping.json --output /private/metrics.json
```

All five inputs are SHA-256 bound in the output, together with the runner file.
Collection must match the exact approved expectations and mode and be complete.
Existing outputs cannot be overwritten. `status: scored` does not assert a release
pass: the release validator's unchanged thresholds, final candidate identity,
staging checks, provider accounting, and separate authorization gates still apply.
Missing or invalid reviews remain failures in the fixed denominators. Answer
cases with missing ranked retrieval traces score zero in enabled-mode Recall@k;
clarification cases require the listed-candidate review. Disabled Recall@k is
N/A. A context-free clarification scores 1 only when its valid supported review
records a clarification, lists no candidate game, and no search evidence exists.
No scoring command performs provider calls.
