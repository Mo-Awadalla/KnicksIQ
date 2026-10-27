# Analyst boundary fixes

This batch fixes four contracts identified on integration commit `6e89d3a`. It does not change
the deployed services, model choices, input limits, or release approval.

## Results

- The new regression file failed nine cases before the fixes and passed two controls. All eleven
  now pass. That initial backend run passed 450 tests. The follow-up correction below passes 461.
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

## Compound-request and coverage correction

The first authority rule had a regression. The scalar parser selected one member of a
compound request, so all player calls could return rebounds or averages. Setting the scalar
to unspecified repaired dispatch but exposed another problem. Planning and fallback still
treated unspecified statistics as points.

The corrected scope carries `requested_metrics` and `requested_aggregations`. Dispatch selects
within those sets. Deterministic prefetch fetches simple compound requests within the existing
tool limit, and fallback retains all requested facts. Player tools reject the team-only margin
metric as unsupported instead of raising an attribute error.

The new direct regressions initially reported six failures and two passing controls. Two
public API regressions then reproduced missing facts after a model failure. All 22 boundary
regressions now pass, including an additional unrequested-metric control. The complete backend
suite passes 461 tests. The existing 27-session, 64-turn scope audit still passes.

`compound-live.json` preserves the failed intermediate API run. After the requested-set fix,
`compound-live-after.json` records both questions delivering every requested metric. The
three-stat answer used factual fallback and delivered 30.6 points, 3.2 rebounds and 7.1 assists
per appearance. The total-and-average answer passed model review and delivered 398 total
points and 30.6 per appearance. This is a two-question smoke check, not a new benchmark.

The rejected repair had copied game ID 29 from backend coverage text. That was a producer-side
contract mismatch, not an invented model number. Coverage now describes non-appearances and
missing data without identifiers. Review retains those limitations. The targeted repeat in
`coverage-repair-after.json` passed review with the numeric gate unchanged. The original failed
artifact is retained.

Run `tools/release/verify_compound_queries.py --live --out <path>` with the same local database
and Go environment as the repair check to repeat the two compound API questions.

The fake reviewer report's `comparisons-004` rejection does not establish a factual regression.
That recorded answer is a clarification with no claims. The fake labels every span factual and
supplies no citation. Real reviewer instructions classify that text as conversational.


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
