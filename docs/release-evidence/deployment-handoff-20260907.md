# Production deployment handoff

Application deployment is pending. Current candidate is `a460cd28c7f63bfaa2f03f5a9a5bce120b5b5507` after the four border fixes. The follow-up passes production frontend build, two report browser tests, formatting and the design detector; desktop/mobile review shows no overflow. Rebind the final release evidence to this candidate before deployment. Earlier full-suite tested source commit: `ec62fdaba2768b73630c91e13c8d088dff03ed72` on `codex/production-ready-20260907`.

The isolated checkout is `/tmp/knicksiq-production-ready-20260907`. The original working tree is preserved, including concurrent homepage edits.

## Completed

- 312 backend/tool tests, Ruff and Pyright pass.
- 46 frontend tests and 27 production-build browser tests pass. Lint has zero errors and two existing warnings; formatting passes.
- API and web Docker builds pass; Render CLI blueprint validation passes.
- Independent review of the preceding V5 runtime capture passes all 120 proposed fact/disposition checks: 58 answers, 53 clarification requests and nine refusals. Final changes improve wording; labels are unchanged.
- Local production-profile load: 2,457 requests, zero errors, ten concurrent distinct analyst questions; archive p95 50 ms, analyst p95 751 ms. Optional providers were disabled/degraded; these are not live Render latency results.
- Local vector index: 15,864 possessions, 101 games, 2,950 box-score records and 101 reports. Stored counts, game filters and release isolation pass. No aliases were promoted.
- Production database was backed up, independently restored and migrated successfully to `0005_player_analytics_views`. All 101 games and reports remain available; active data version is unchanged.
- Production web CSP was corrected. Application deployments remain unchanged.

## Remaining prerequisites

1. Restore Qdrant Cloud access. Both TLS ports 443 and 6333 return `Connection reset by peer` before authentication. The cloud dashboard is open in Chrome but requires sign-in. After access returns, verify production collections, alias rollback targets, filters and semantic evaluation.
2. Owner review of the prepared batches:
   - [Report template, correction policy and audit summary](report-audit-20260907/audit.md): 101 corrected drafts, zero unresolved audit findings. One real backward scoreboard correction is preserved, and selected intervals crossing it are excluded.
   - [Evaluation proposals](evaluation-label-review-20260907/review.md): all 120 fixed questions, with canonical facts and explicit clarification/refusal decisions.
   - Audit JSON SHA-256: `89fabf996ee7f66eab7f0830468bc0640d64d9abfd3e3e423d3873c60ab7f03a`.
   - Labels SHA-256: `7c3c549e6a540f4ce03a3fa4ba38821ddc6f7641c9d081270cff8607ec9b007e`.

The [repository release policy](../release-checklist.md) says: “Do not fill approvals on the owner's behalf.” These batches have not been approved or activated. The corrected bundle remains an unreviewed candidate.

After prerequisites pass, finish the hash-bound release gate, deploy the exact tested source using Render CLI, then verify live routes, answers, reports, dependencies and load. Preserve coordinated rollback for application deployments, active data and Qdrant aliases.

See [final verification](final-verification-20260907.json), [release record](release-record.json), and [rollback snapshot](rollback-snapshot-20260907.json) for details and scope limitations.
