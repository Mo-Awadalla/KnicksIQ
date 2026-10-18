# Proposed release policy: verification and delivery are separate stages

Status: proposal requiring explicit owner approval; not an implemented gate change.
The existing release validator still requires shadow at 0.1. No production
setting or existing gate is waived by this document.

## Pre-promotion verification

Retain the `shadow_dependencies` gate and require recorded configuration
`answer_mode=shadow`, `shadow_sample_rate=0.1`, evidence loop enabled. Bind it to
the candidate SHA, content hash, expectation hash, infrastructure identity and
verification time. Sampled turns exercise the same budget reservations and
evidence validation as primary turns, but deliver factual fallback. Unsampled
turns deliver factual fallback without model calls. Require rate 0, rate 1 and
both outcomes at 0.1, session replay/conflict, budget denial, validation failure
and dependency recovery evidence. Record sample membership and model calls.
Local fixture checks establish behavior only; staged infrastructure checks
remain separate and cannot pass before candidate resources exist.

## Intended user-facing release

Record `launch_configuration.answer_mode=llm_primary`, with deterministic
fallback, current evidence validation, allowlist and $2 monthly cutoff intact.
Primary turns must not be sampled. Add an explicit validation of this intended
configuration instead of requiring the final serving mode to remain shadow.
Require both the preceding shadow gate and primary-mode production-profile
verification before the release can be eligible for promotion.

Proposed validator delta: replace the current single `configuration` mode check
with **two required** checks: `pre_promotion_configuration` must be shadow/0.1;
`launch_configuration` must be llm_primary. Neither can satisfy the other.
Keep every existing required check, quality threshold, 120-case denominator,
content-bound approval and final record-hash authorization. Require an owner
approval bound to this policy document before implementing the validator delta.
A later implementation changes tracked code and therefore requires a new
candidate SHA and its CI; this proposal alone does not unblock the old gate.

## Authorization sequence

1. Request staging-write authorization naming the destination, candidate bundle,
   release version and physical collections. No alias promotion, active release
   change or serving deployment is included.
2. After authorized staging creates those resources, verify staged schema,
   loaded rows, vectors, counts, payloads, filters, release isolation, dependencies,
   rollback availability and both configured modes. Keep evidence local. Paid
   evaluation traffic needs its own bounded authorization; no production load
   or failure injection.
3. Complete the release record and hash it. Obtain final promotion authorization
   bound to that exact hash, SHA, content, targets and rollback plan. Only then
   deploy/promote/activate as expressly authorized and run served acceptance.

Approved report content may retain its existing approvals only when the exact
artifact hashes and approval scope still match. Old CI and historical runtime
evidence retain their original commits. Provider compatibility smoke success
cannot replace either 120-case evaluation or any quality gate.
