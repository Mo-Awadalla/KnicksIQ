# Release policy: verification and delivery are separate stages

Status: owner decision on 2026-10-20 supersedes the former required shadow
stage. Launch goes straight to `llm_primary`; this document neither changes
production configuration nor grants final promotion authorization.

## Readiness

Readiness requires the intended `llm_primary` launch configuration, the enabled
evidence loop and every existing release check on the exact tested commit. It
does not require a pre-promotion shadow configuration, `shadow_dependencies`
or `shadow_evaluation`.

Keep the frozen 120-case cohort and all 50 semantic members. Retrieval answers
use Recall@k with k = max(5, number of complete targets); target lists are never
capped. Clarification cases score the candidate games explicitly listed in the
reviewed answer. Preserve numeric/entity, citation, paraphrase, abstention,
source identity, rollback, content-hash and owner-approval gates.

The planned `openrouter_monthly_cutoff_usd` is $20. Apply that value only during
an explicitly authorized deployment. This branch leaves current Render settings
unchanged. Readiness remains separate from final launch approval and the
owner-controlled digest of the completed record.

Optional shadow execution remains available for separately authorized
evaluation. It is not a readiness or deployment prerequisite and cannot replace
any required release check.

## Authorization sequence

1. Resolve and record the exact destination, candidate bundle, release version,
   physical collections and rollback targets. Do not promote aliases, activate
   data or deploy a serving release without explicit authorization.
2. Complete every required readiness check on the exact candidate commit,
   including primary and service-disabled evaluation, staged dependencies,
   rollback availability and the existing quality thresholds. Keep evaluation
   evidence local.
3. Complete and hash the release record. Obtain owner approval bound to its
   exact content and tested commit. Readiness does not create or imply this
   approval.
4. Deploy, activate or promote only as expressly authorized. Run the required
   served acceptance checks and restore the coordinated targets on failure.

Approved report content remains usable only while its exact artifact hashes and
approval scope match. Historical CI and runtime evidence retain their original
commits. Provider compatibility smoke success cannot replace the fixed-cohort
evaluation or any quality gate.
