# Shadow sampling regression design (before implementation)

Exercise HTTP /analysis/query with the evidence loop enabled, synthetic SQL data,
a disposable real Redis, and a protocol-only provider fixture. No paid calls.

Failure cases: rate 0 still invokes a model; rate 1 fails to invoke it; a known
sampled hash at 0.1 is skipped; a known unsampled hash at 0.1 invokes it; an
unsampled turn loses factual answers/citations or session commits; shadow leaks
validated model delivery; llm_primary is incorrectly sampled; replay repeats
model work or changes its committed response; changed replay payload bypasses
conflict protection; missing budget invokes the adapter; malformed model output
bypasses evidence validation instead of falling back. Existing adversarial
contract tests additionally cover reservations, races, timeouts and validation.

Repeat: TEST_MODE=true uv run pytest apps/api/app/tests/test_analyst_shadow.py
--junitxml=docs/release-evidence/reconciliation-20260928/shadow.xml

# Local restore/mapping/rehearsal design (before script)

Fail closed on non-loopback SQL configuration, production endpoint reuse, a
bundle/approval hash mismatch, duplicate/missing canonical identity, differing
restored row fields, foreign-release citations, unresolvable calculation
receipts, unresolved semantic targets, accidental provider access, source
mutation during index build, mismatched index counts/vector dimensions,
missing report title/summary, wrong-release filter leakage, failed rollback,
or incomplete/failed HTTP responses. Rehearsal answers are not label gold.
No production-derived payload may leave the local host. Keep the full 120-case
quality evaluations pending frozen expectations and separate spend approval.
