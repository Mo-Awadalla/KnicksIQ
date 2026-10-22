# Main-based analyst reconciliation

The owner chose reconciliation from current main after PR #35 reported conflicts. Base commit
is `b2f25cc`. The source branch remains available in PR #35. Neither pull request authorizes a
merge or deployment.

## Acceptance

The new branch must preserve main's native statistics, complete evidence and guarded evaluation
contracts. It must support Go Chat Completions for the writer and Responses for the reviewer,
preserve conversation scope across greetings and refusals, and answer compound statistics
without collapsing them to one metric. The final commit must pass hosted backend, frontend,
container and security CI.

## Decisions

| Area | Reconciliation |
| --- | --- |
| Native statistics | Keep main's threshold, leader, profile, team-comparison, quarter and canonical-narrative calculations. Do not replace them with the older branch's tool registry or calculators. |
| Evidence and repair | Keep main's sealed complete claim domains, mandatory claim groups, complete cited receipts and flat repair prompt. These already solve the older branch's evidence and repair-shape issues. |
| Provider | Port mixed wire protocols, random provider session IDs, configured token-rate estimates and a separate reviewer model. Preserve existing OpenRouter route and price-cap checks. |
| Output caps | Keep library defaults at main's 1,200 tokens. The Go blueprint explicitly selects 1,600 writer and 3,000 reviewer tokens. Input and evidence ceilings stay unchanged. |
| Session | Commit greetings without replacing the topic, preserve the original state for policy refusals, and return the canonical stored response if another execution already committed the same turn. Keep main's lease-owner requirement for uncommitted turns. |
| Compound requests | Preserve requested metric and aggregation sets in the existing resolver. Native preparation fetches the requested statistics, and complete-claim validation applies to all resulting facts. |
| Release policy | Keep main's frozen evaluation and approval files unchanged. Its counted OpenRouter evaluator remains bound to the previously authorized model and fails closed when the blueprint no longer matches. New Go release-quality evidence is required before claiming promotion readiness. |
| Historical evidence | Keep PR #35 as the archive rather than copying its large SQLite, Qdrant, benchmark and generated graph files into this PR. |

## Baseline and reproducible checks

The first test launcher came from an APFS-copied virtual environment and pointed at the old
worktree. The valid baseline uses this worktree's Python interpreter and `python -m pytest`.
It passed 1,310 tests. An earlier run timed out before completion and is not a pass.

Before application changes, the new transport and boundary checks reported seven failures.
They reproduce unsupported Go Responses transport, session loss across interludes, collapsed
compound metrics, and total-versus-average collapse. A separate Redis check reproduced a
second execution failing to return the canonical committed response.

Run the suite with a clean environment:

```sh
env -i HOME="$HOME" PATH="$PATH" TEST_MODE=true uv run --frozen python -m pytest apps packages tools/report_audit -q
uv run --frozen python -m ruff check apps packages migrations
uv run --frozen python -m ruff format --check apps packages migrations
uv run --frozen python -m pyright apps packages migrations
```

`test_opencode_transport.py` runs a real local HTTP server. It checks both protocols and token
cost normalization without sending credentials or requests to an external provider.
`test_reconciled_boundaries.py` exercises the public API with SQLite and real isolated Redis,
and checks native statistics with and without prior conversation state.

The deployed Go key must be supplied through `AI_API_KEY`. No secret is committed. Configured
list-price accounting is an estimate of subscription usage, not a provider billing receipt.
The reviewer is an answer reviewer, not a retrieval reranker. The blueprint remains manual-deploy.

## Runtime evidence

`browser-before.json` records a real browser failure after the first session patch. Session
identity survived, but the assists follow-up widened December to the whole archive.
`browser.json` and `browser-after.png` record the corrected conversation. Revisions advance
from 1 through 4, and points and assists cite the same 13 December appearances.

`api-deterministic.json` and `api-go.json` each contain the six-turn API check. All four checks
pass, including compound metrics and total-versus-average completeness. In the Go run, two
substantive turns passed independent Luna review and two used factual fallback. The recorded
served models match DeepSeek Chat and Luna Responses. This small smoke is not a benchmark
or public-release certification.

Repeat the smoke against the local restore with Redis on port 56500:

```sh
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
REDIS_URL=redis://localhost:56500/14 AI_PROVIDER=disabled \
ANALYST_EVIDENCE_LOOP_ENABLED=true ANALYSIS_ANSWER_MODE=deterministic \
RAG_QDRANT_ENABLED=false PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE=100000 \
uv run --frozen --package knicksiq-api python tools/release/verify_main_reconciliation.py \
  --out release-artifacts/main-reconcile/api.json
```

For a live repeat, supply the Go settings from the blueprint and `AI_API_KEY` in the process
environment, then set `ANALYSIS_ANSWER_MODE=llm_primary`. Do not source a production database
URL. The smoke creates only ephemeral conversation state and does not change archive data.

The first complete post-change suite reported four failures. One pinned coverage wording,
one lost a claim to empty-selector prompt overhead, and two expected generic compatible hosts
to omit reasoning fields. The wording pin was removed, empty selector lists no longer consume
the bounded prompt, and Go-specific effort remains separate from ordinary compatible hosts.
All 79 targeted compatibility cases pass after those corrections. The final hosted CI result
is the publication gate.

At `2bed96a`, the local suite passed 1,318 tests, and all hosted CI checks passed.
Publication is through PR #36. PR #35 remains unchanged as the old integration archive.
Hosted CI status is attached to the exact head commit on PR #36.

## Review follow-up

Two named compound questions on one game still entered the unqualified-profile path. A scalar
metric of `None` can mean multiple metrics, not only no metric. Profile, discovery and record
guards now check the requested metric set too. Both public API cases failed with no facts
before the correction and now deliver the requested points and assists.

The staging verifier now checks the `model_provider` health dependency. Its full seven-request
preflight passed against the actual local API and Vite proxy. This is not a Docker restart
verification. The same run exercised both named compound questions against the real archive.
See `review-followup.json`.

Targeted profile and payload checks pass 29 cases. Provider compatibility checks pass 31 cases.
Go session headers stay on configured mixed-protocol hosts rather than ordinary OpenRouter
calls. Ruff, formatting and Pyright pass. The new head requires its own hosted CI verdict.
