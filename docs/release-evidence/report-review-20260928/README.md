# Report correction review — content approved, not activated

This batch reuses the existing `canonical-score-intervals-v2` proposal in
`release-artifacts/2025-26/release-corrected-unreviewed.json`. Regeneration from the
unchanged source rows reproduces all 101 replacement reports exactly. It does not
change canonical basketball rows, select a new policy, grant approval, or publish.

The read-only audit of all 101 reports in the local baseline finds 101 reports with
unresolved interval claims, including 40 contradictory single-quarter clock ranges.
All 101 final scores and 303 player lines match. The replacement passes all 101
reports, 303 player lines and 303 scoring interval checks. The original review audited the local source snapshot. The subsequently authorized
fresh full production audit below confirms that snapshot matches production.

The exact content is in `reports.diff`, `replacement-reports.json`, and
`rollback-reports.json`. `review.json` contains source-file hashes, canonical data
identity, per-report before/after hashes, both full audits and the policy. `SHA256SUMS`
binds those four files and the observed production binding. Rollback reports are the local baseline snapshot; verify they
match production before using them for rollback. The existing production backup and
app/index rollback targets must also be pinned again before activation.

## Report 80 independent reproduction

Game `0022501168` (NYK–BOS, 2026-04-09):

| Interval from diagnosis | Inclusive events | Baseline NYK–BOS | End NYK–BOS | Verified totals |
| --- | --- | --- | --- | --- |
| Q3 06:11–02:22 | 260–296 | 72–62 (event 259) | 76–78 | BOS 16–4 |
| Q3 11:41–09:33 | 222–231 | 54–53 (event 221) | 66–57 | NYK 12–4 |

Neither interval was unanswered. These reproduce the diagnosed ranges independently
of the application detector. The existing replacement may select different ranges;
each replacement is checked against its own exact boundaries and scoreboard facts.
A compact fixed fixture and regression assertions preserve these reproductions in CI.

## Publication boundary

Owner approval must bind the actual batch hashes, template and existing scoreboard
exception (game `0022500125`, event 198, away score 66→65). Do not fill approvals on
the owner's behalf. Publish only through `docs/release-checklist.md` after the current
production baseline, final code revision, data version and rollback targets are pinned.
The application must see a new release/content identity; replacing report text within
an unchanged version could leave prior analyst evidence apparently current.

After approval, verify report list summaries, report detail API and report page against
the approved stored values. Rebuild candidate index artifacts through the existing
release process and promote aliases only at activation. `rag_index.py` currently embeds
report title and summary only; these do not change in this interval-only correction.
Other report consumers and cached analyst evidence must nevertheless move to the new
release identity. Verify serving caches/index copies against actual payloads instead
of assuming all indexed content includes interval prose. No cache or index mutation
has been performed by this preparation.

Reproduce with:

```sh
python3 tools/report_audit/prepare_review.py \
  release-artifacts/2025-26/release-candidate.json \
  release-artifacts/2025-26/release-corrected-unreviewed.json \
  --output docs/release-evidence/report-review-20260928
uv run pytest tools/report_audit apps/api/app/tests/test_reports_api.py -q
```

## Historical partial binding — superseded by the fresh full audit below

The already captured `reliability-20260928/live-before.json` identifies active release
`1`, version `2025-26.20260714.1`, manifest
`269b0db08fd07a1dbe53e6a388a313fe6afc04ace3cd3294dc9610c981c4b9fd`.
All 101 stored `content_sha256` values match the local baseline when reconstructed
using the existing release loader's representation (internal game ID and release ID).
Report 80's separately captured public title, summary and three interval narratives
also match the local baseline. See `observed-production-binding.json`, now included
in `SHA256SUMS`; this comparison made no additional production requests.

These stored hashes are ingestion-time metadata. They were not freshly recomputed
from all current production rows, so they cannot exclude an in-place row change.
The full fresh canonical/report-row audit and production rollback export remain
unverified. The rollback snapshot above remains a local baseline, not a freshly
exported production backup. The September 7 canonical-row comparison is historical.

A prepared `bind_production.py` utility establishes a repeatable-read, read-only
transaction and compares every canonical and report row. Its attempted production
read failed in the sandbox; automatic approval review rejected escalation because
it considered production report contents and metadata export insufficiently authorized.
No production snapshot was written. Obtain explicit approval for that read/export
before rerunning the utility; no workaround or retry was used. Owner content approval
and activation remain separate, unchanged gates.

## Owner approval and fresh production binding (2026-09-28)

The owner explicitly approved the exact 101-report content hash in this chat, including the existing policy and documented scoreboard exception. `owner-content-approval.json` records the decision. The separately approved read-only export completed in a repeatable-read/read-only transaction: every row in all 8 compared collections matches the baseline. `production-binding.json` holds the fresh audit; `production-rollback-reports.json` is the local rollback snapshot. No production writes occurred.

`approved-bundle.json` identifies the validated local bundle with a new release version. Only reviewed flags, approval metadata and the version changed; all approved narrative hashes and canonical basketball rows remain unchanged. The bundle is not staged or activated. Earlier unapproved snapshots and their hashes are intentionally preserved as the exact reviewed input. Evaluation-label and launch approvals and remaining release checks are still required. Production-derived evidence must remain local unless separately authorized for publication.
