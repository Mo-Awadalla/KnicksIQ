# Release verification and authorization

The season-chat cutover retires the proposed shadow/primary split. There is one
request-owned streaming conversation path. No deterministic answer fallback or
shadow sampling configuration remains.

## Pre-promotion verification

The validator requires `conversation_protocol` evidence for real local HTTP chat
checks in `apps/api/app/tests/test_chat_http.py` and `test_chat_fault_http.py`.
Bind the evidence to the tested commit, content hashes and infrastructure identity.
Scripted upstreams establish protocol behavior, not real-provider voice or quality.

The deployment blueprint must keep `OPENROUTER_MONTHLY_CUTOFF_USD` at `2` and
`AI_CHAT_MODEL` inside `OPENROUTER_ALLOWED_MODELS`. No change authorizes a paid call,
production ledger initialization, deployment or data mutation.

Keep all other required checks, quality thresholds, the 120-case denominator,
content-bound approvals and final record-hash authorization. Numeric gold values
and all original semantic case IDs remain fixed. The public-citation gate reports
`inapplicable: public citations retired; owner-approved rubric migration pending`.
It does not pass as private factual evidence. The validator remains blocked pending
an owner-approved rubric migration. The historical `analyst_p95_ms` and
`archive_p95_ms` warm-load metric names remain, measuring chat turns and readiness.

## Authorization sequence

1. Request staging-write authorization naming the destination, candidate bundle,
   release version and physical collections. No alias promotion, active release
   change or serving deployment is included.
2. After authorized staging creates those resources, verify staged schema,
   loaded rows, vectors, counts, payloads, filters, release isolation, dependencies,
   rollback availability and the conversation configuration. Keep evidence local.
   Paid evaluation traffic needs its own bounded authorization. No production load
   or failure injection is included.
3. Complete the release record and hash it. Obtain final promotion authorization
   bound to that exact hash, SHA, content, targets and rollback plan. Only then
   deploy/promote/activate as expressly authorized and run served acceptance.

Post-deploy smoke checks only `/health/live` and `/health/ready`, including the
expected active `data_version`. It never submits a paid question.

Approved report content may retain its existing approvals only when the exact
artifact hashes and approval scope still match. Old CI and historical runtime
evidence retain their original commits. Provider compatibility smoke success
cannot replace the 120-case evaluation or any quality gate.
