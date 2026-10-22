# Analyst boundary fixes

This batch fixes four contracts identified on integration commit `6e89d3a`. It does not change
the deployed services, model choices, input limits, or release approval.

## Results

- The new regression file failed nine cases before the fixes and passed two controls. All eleven
  now pass. The full backend suite passes 450 tests.
- In real Chromium, a Brunson-in-December question followed by a greeting, a betting refusal,
  and "And his assists?" keeps the same session and advances revisions 1 through 4. The last
  answer gives 7.1 assists across 13 December appearances. Before the fix, the refusal discarded
  the session and the next turn asked which player. See `browser-before.png`, `browser-after.png`
  and `browser-after.json`.
- Real-archive tool calls cannot override the resolved metric or aggregation. A conflicting
  assists call for the points question returns the requested 30.6 points average. A conflicting
  average call for total assists returns 92. See `archive-after.json`.
- The 82-game regular-season record review contains both declared claims and two compact
  calculation receipts. Its evidence uses 1,530 bytes, below the unchanged 6,000-byte ceiling.
  Source game-id lists remain server-side. Explicit evidence references are mandatory, not
  silently dropped during packing.
- Three live repair calls through Go returned parseable flat `ProposedAnswer` objects. Luna
  accepted two. The numeric gate rejected the other because its text included an internal game
  identifier that was not an allowed factual value. That live smoke therefore remains `passed:
  false` in `live-repair-after.json`. It is not a benchmark pass or a release-readiness claim.
- The offline follow-up audit remains 27 of 27 sessions and 64 of 64 turns. The existing numeric
  mutation check rejects 324 of 324 wrong-number mutations and accepts all 14 correct controls.
  These checks are not a measurement of the live reviewer's accuracy.

## Contracts

`ResolvedQuery` now carries aggregation. Calculator handlers prefer its metric and aggregation
while leaving unspecified fields model-selectable. The existing aggregate test now asks a
question without a specified aggregation when comparing model-selected totals with averages.

Early replies use the same atomic commit, replay and revision checks as ordinary turns. They
preserve the prior topic and claims without calling the model. No browser-specific exception
was added.

Repairs have their own prompt matching the flat answer schema. The normal action prompt remains
for tool planning and initial answer selection. Prompt and validator labels are now
`analyst-balanced-v5` and `whole-answer-v3`.

`answer_evidence.py` selects declared claims, baseline claims and their receipts, plus explicitly
cited receipts. Checks, reviewer input and delivery share that selection. A statement cannot
borrow an undeclared claim merely because the writer saw it earlier. Current reviewer replay
runners apply the same selection. Historical measurement files stay unchanged.

## Repeatable checks

Run from the integration worktree with a clean test environment:

```sh
env -i HOME="$HOME" PATH="$PATH" TEST_MODE=true uv run pytest apps packages tools/report_audit -q
uv run ruff check apps packages migrations
uv run ruff format --check apps packages migrations
uv run pyright apps packages migrations
```

The local release check needs the restored database and no model credentials:

```sh
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
REDIS_URL=redis://localhost:56500/15 AI_PROVIDER=disabled \
uv run --package knicksiq-api python tools/release/verify_analyst_boundaries.py \
  --out release-artifacts/20261022-boundary-fixes/archive.json
```

With the configured Go credentials and model settings in the process environment, add `--live`
to repeat the three repair-and-review cases. It spends model calls and does not retry for a
better score. Credentials and bearer session tokens are absent from the committed evidence.

The browser run used the real frontend at port 5186 and the real API at port 8176, with the
analyst loop enabled in deterministic mode against the local release. Ask the four questions
in `browser-after.json` in order. No UI response was intercepted or mocked.
