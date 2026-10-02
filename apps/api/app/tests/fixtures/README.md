# Synthetic HTTP archive

`synthetic-archive.json.gz` contains fabricated scores, box scores, events and
reports. Its release identity is `2025-26.synthetic-ci.1`; it is never approved
release content or evaluation gold. Familiar player/team identities and a few
fixed game identifiers exercise existing parser and narrative assertions; the
associated synthetic numbers do not describe those actual games.

The fixture has 101 games, nine Atlanta games across multiple phases, twenty
Knicks roster identities, DNP rows, both All-Star populations, six tied closest
games and two tied twelve-point Boston runs. Scores reconcile independently
across player, team, period and final event rows. The builder reads only tracked
team metadata, never private archives, captured results or evaluation labels.

Rebuild deterministically from the repository root:

```sh
TEST_MODE=true PYTHONPATH=apps/api:packages/basketball-core/src \
  python apps/api/app/tests/fixtures/build_synthetic_archive.py
```

Expected SHA256:
`122f26722193a87349d7183ab42a479b8603c779b69f0a34bc1035356c556707`.

To repeat the approved-archive checks locally, explicitly set
`KNICKSIQ_APPROVED_BUNDLE` to the existing approved gzip file. That path retains
the original required SHA256 `549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b`.
CI does not upload or download that private source bundle. Its backend artifact
retains synthetic HTTP responses, source receipts, accounting journals and JUnit.
