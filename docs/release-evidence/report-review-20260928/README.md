# Report correction review — prepared, not approved or activated

This batch reuses the existing `canonical-score-intervals-v2` proposal in
`release-artifacts/2025-26/release-corrected-unreviewed.json`. Regeneration from the
unchanged source rows reproduces all 101 replacement reports exactly. It does not
change canonical basketball rows, select a new policy, grant approval, or publish.

The read-only audit of all 101 reports in the local baseline finds 101 reports with
unresolved interval claims, including 40 contradictory single-quarter clock ranges.
All 101 final scores and 303 player lines match. The replacement passes all 101
reports, 303 player lines and 303 scoring interval checks. This is an audit of the
local source snapshot; it is not a fresh audit of the current production database.

The exact content is in `reports.diff`, `replacement-reports.json`, and
`rollback-reports.json`. `review.json` contains source-file hashes, canonical data
identity, per-report before/after hashes, both full audits and the policy. `SHA256SUMS`
binds those four files. Rollback reports are the local baseline snapshot; verify they
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
