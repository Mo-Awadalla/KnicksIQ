# Candidate evidence, 2026-10-21

Tested code: `976eb7c38e553844e3e992f89a3fa6e3a4560d28`.
Dataset: `2025-26.20260928.1`.
Approved source bundle SHA-256: `549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b`.

This packet records observed verification, not release eligibility or owner approval.
The evidence commit is separate from the tested code commit. Historical receipts
retain their original commits; they have not been relabeled as final-candidate runs.
The [artifact manifest](artifact-manifest.json) binds the public files and protected
private archive, including the unmodified captures and executable diagnostic harnesses.
Recompute the draft facts without model calls using
`uv run --offline --frozen --package knicksiq-api python tools/release/compute_launch_set.py`.

## Observed on the final code

| Evidence | Observed result | Boundary |
| --- | --- | --- |
| [Hosted CI](hosted-ci.json) | Security, backend, frontend and containers passed on the exact tested commit | Not the official release evaluation or hosted acceptance |
| [20 launch observations](launch-observations.json) and [independent review](launch-review.json) | All 20 HTTP responses were 200 and all final answers agreed with independent raw-bundle computation; 16 model-validated, four accurate native fallbacks | One final diagnostic capture, not an approved quality score or latency benchmark |
| [Cloud projection](cloud-identity.json) and [review](cloud-review.json) | Four candidate collections reused; zero upserts; production aliases unchanged | Locally restored candidate mapping, not production database mapping |
| [Dense retrieval](cloud-search-smoke.json) | Stored hits returned for games, box scores, reports and possessions; game/date and possession-period assertions passed | Four filtered queries do not establish overall recall |
| [Fresh report audit](../report-audit-20261020/final-candidate.json) | 101 report hashes and score summaries, 303 player lines, zero unresolved reports | Owner template/exception/audit approval and active archive verification remain missing |

The launch capture retained every case and warning. Three final fallbacks followed
rejected model wording. The fourth, `launch-003`, returned all 17 qualifying Towns
rebound games after `ValueError: Complete requested claim requirements exceed model
input budget`, with zero model calls. Follow-up setup turns were separately reviewed;
`launch-019`'s setup was an accurate fallback. No provider/schema failure was observed.
These outcomes must not be reported as 20 model-validated answers.

The public observation projection preserves exact questions, answers, warnings and
runtime classifications. Full unmodified captures contain opaque local session tokens
and stay private with mode `0600`; their hash and individual line hashes are recorded.
No case, answer or warning was removed from the public projection.

The report audit was actually re-executed on the final code. Its full audit is
byte-identical to [the retained audit](../report-audit-20261020/audit.json); the earlier
[receipt](../report-audit-20261020/receipt.json) remains historical. The MIL scoreboard
correction in `game:0022500125` lies outside the selected report intervals. This does
not make its whole-game play-by-play monotonic: the draft run/lead adjudications
explicitly exclude that game from their 100-game verified population pending review.

## Earlier controls retained

- [Full pre-push CI-equivalent receipt](../fan-ci-closure-20261021.json): 1,406 backend
  tests passed before publication, with source-file hashes and the original worktree
  provenance retained. Exact published-head and merged-head CI then passed.
- [Opponent-count and reference controls](../fan-opponent-count-20261021.json) and
  [reference grammar](../reference-grammar-20261021.json) retain their actual captures,
  including the accurate but unvalidated Hart fallback. They are not rerun or rewritten
  to manufacture an all-model-success result.
- [Production backup and isolated restore](../rollback-20261020/backup-restore.json)
  verified the dump and all 17 public table counts. This was not a production restore.
- [Hosted availability diagnosis](../hosted-health-20261020.json) retains both observed
  public 503s. Cold-start/wake behavior is an inference, not a proven request-level cause.
- [Manual keepalive smoke](../keepalive-manual-20261020.json) passed. It proves neither
  scheduled continuity nor first-cold-request availability, p95 or error rate.
- [A scheduled keepalive run](keepalive-scheduled.json) also passed at 01:02 UTC.
  This later observation does not rewrite the earlier zero-run snapshot, demonstrate
  uninterrupted ten-minute coverage or prove that the API serves the tested commit.

## Owner gates still closed

1. Review the [20 adjudication proposals](../evaluation-contract-20261019/adjudication-drafts.md)
   and their [machine file](../evaluation-contract-20261019/adjudications-draft.json).
   These include strict lead reversal for lost-lead/collapse, tie-inclusive erased
   deficits, descriptive rather than causal run definitions, and the scoreboard exception.
   The proposal file SHA-256 is `bf7def583f977cc760ad77d98e07480f5e03b0da39fe15867eb41a3e0a1b88a3`.
2. Review the separate [20-question launch set](../launch-set-20261020/README.md).
   Its JSONL SHA-256 is `eddd13fa7a85ab92bcae770944523d55ef285f3fc55dd3ac7e749c0a7478bd2d`.
   It remains DRAFT despite this diagnostic's correct final answers.
3. Freeze and obtain hash-bound approval for the official evaluation contract, then run
   the guarded primary and service-disabled collection and review/scoring process.
   Preserve all original 120 questions and the fixed 50 semantic members, complete
   target lists, adaptive k = max(5, target count), and the 0.95 recall threshold.
   No official 120/50 quality score is claimed by this packet.
4. Obtain the report template, exception and final audit approvals; verify the active
   production mapping before treating candidate projection evidence as served identity.
5. Complete hosted acceptance with p95 below 15 seconds, error rate below 1%, and a
   successful first request after a controlled idle period. Current observations do
   not pass this gate. Keepalive success is not a substitute.
6. Complete the release record and obtain owner approval bound to its digest and named
   tested commit. Only an explicitly authorized deployment may change the monthly
   cutoff from $2 to $20, activate the dataset or promote candidate aliases.

No deployment, live alias promotion, Render plan change or production budget change
was performed to prepare this packet. Launch remains direct `llm_primary`; no mandatory
shadow stage has been reintroduced. See [the release policy](../../release-policy-proposal.md)
and [the deployment runbook](../../render-deploy.md).
