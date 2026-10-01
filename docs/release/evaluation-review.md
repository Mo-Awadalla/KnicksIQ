# Local evaluation review interface

This is an internal workflow specification, not approved release labels or evidence.
All 120 original cases, including all 50 original semantic cases, remain required.
Unresolved targets block freezing; frozen expectations still require a separate
owner approval bound to the exact expectation file SHA-256.

Capture the service-disabled cohort with the existing runner's `--mode disabled`.
Primary and shadow collection accept an explicit `CountedRun` dependency. It
installs the counted transport, requires environment verification before the
cohort and payload verification before every provider request, preserves partial
evidence, and stops even if the analyst masks a provider failure with fallback.
The command-line collector has no default live verifier: paid execution remains
blocked until real monthly accounting, current conservative provider bounds,
isolated resource identities and billed dependencies are independently verified.
Shadow request IDs and membership are fixed before calls; its durable journal
cap must match six times the actual selected count. The accounting snapshot is
cumulative across attempts; `paid_requests` is the current attempt’s delta.

Reviewers inspect each complete answer, its typed facts and scope, and the actual
receipts. They record contiguous assertion spans covering the entire answer.
Allowed classifications are `factual`, `clarification`, `refusal`, and `nonfactual`.
A factual assertion names `canonical_fact_ids`: the runner's canonical JSON digest
of each applicable frozen fact object. It also names `citation_evidence_ids` that
actually appear in the response citations. The runtime mapping must map each cited
reference to a canonical source supporting the named frozen fact. Every expected
fact must be covered for an answer review to be complete.

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
staged evidence, provider accounting, and separate authorization gates still apply.
Missing or invalid reviews remain failures in the fixed denominators. Missing
semantic retrieval stays zero for live-mode Recall@5; disabled Recall@5 is N/A.
No scoring command performs provider calls.
