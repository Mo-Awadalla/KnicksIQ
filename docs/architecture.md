# KnicksIQ architecture

## Production system

KnicksIQ serves one immutable Knicks 2025–26 archive. Render hosts a static
React application and a free, read-only FastAPI service. Neon Free Postgres is
the authoritative store. Render Free Key Value supplies ephemeral shared rate
limits, answer caching, and AI budget state. Qdrant Cloud holds release-versioned
retrieval indexes. OpenRouter plans bounded retrieval and phrases evidence that
KnicksIQ retrieved or computed. Sentry receives scrubbed errors and low-sample
traces.

Postgres and one validated active `dataset_releases` row are required.
Qdrant, Redis, and OpenRouter are optional at request time. Their failure must
not prevent deterministic factual answers.

## Immutable release boundary

NBA access, normalization, reconciliation, report generation, and manual report
review happen offline. The release tools export a versioned bundle containing
games, events, period scores, team and player box scores, teams, players, and
one hash-bound reviewed report per game. The loader verifies the supplied
SHA-256, validates the bundle, and imports it transactionally and idempotently.

All public basketball queries are scoped to the active validated release. The
API does not run migrations or mutate archive data at startup. Because Render's
Free tier does not support pre-deploy commands, the release operator runs the
expand-only Alembic migration against Neon before deployment.

Bundle loading and deployment share `activate_release`. PostgreSQL activation
uses a transaction-scoped advisory lock before superseding the previous release;
locking individual candidates alone does not prevent two concurrent active releases.

## Runtime request flow

The web application calls the public API anonymously. Archive endpoints read
the active release directly from Postgres. `POST /analysis/query` first refuses
explicit unsupported/live/tactical requests. In `llm_primary`, a schema-bound
planner selects allowlisted searches and fact tools; the server validates its
filters and injects the active data version. Qdrant supplies game, box-score,
report, and possession evidence while Postgres analytics compute canonical
numeric facts. The answer model emits evidence-linked claims, and the server
rejects unsupported evidence IDs, entities, or numbers before rendering prose.

`deterministic` bypasses planning and synthesis. `shadow` returns the
deterministic response and evaluates a sampled LLM candidate in a background
task. `llm_primary` returns the validated LLM answer. Any vector, model, Redis
budget, timeout, parsing, or validation failure returns the deterministic answer
with `degraded=true`.

Narrative questions always use the release-bound analyst evidence loop, including
when `ANALYST_EVIDENCE_LOOP_ENABLED` is false. That flag still selects the loop for
other question types; the legacy deterministic table/player handlers remain.
The former document/possession narrative response path has been removed.
Pinned-game narratives cite the game's final score. Quarter and clock-window
narratives cite only matching release-scoped play-by-play rows, not whole-game
averages; the receipts do not establish causes.
Modern turns resolve replay and turn-identity conflicts before archive-domain
admission. Out-of-domain and missing-data turns use the same session commit
protocol without running the model; mixed requests retain supported archive portions.

Production routing deliberately excludes ingestion, job enqueue, run
detection, report creation/deletion, Swagger, and OpenAPI. Workers and MCP are
offline/development packages, not deployed production services.

## Data model

`dataset_releases` owns activation and validation metadata. Basketball rows are
release-scoped through `release_id`; a game identity is unique inside a release.
The core hierarchy is:

```text
dataset_releases
  games
    game_events
    period_scores
    team_game_stats
    player_game_stats
    scoring_runs
    bad_stretches
    reports
```

Teams and players supply entity metadata. Documents/chunks support offline
index generation. Jobs exist for offline/development workflows only.

Offline jobs persist their SQL status row before RQ publication. Only a queued job
may start, and work completion requires a started job. Publication failure may fail
a still-queued job without overwriting a claimed one. Terminal jobs cannot restart.
Event replacement and feature detection lock the same game row.
Replacing events invalidates cached runs and bad stretches in the same transaction.
The season-cache CLI still gates overall readiness on successful analysis and RAG
artifacts; NBA retries each acquire their own rate-window admission.
See `docs/data-model.md` for field-level detail.

## RAG indexing

The offline indexer builds immutable Qdrant collections for game summaries,
box-score facts, reviewed reports, and possession chunks, then emits validated
candidate aliases. Promotion changes stable aliases in one operation and refuses
missing targets or physical-collection name collisions without deleting data.
Legacy name migration is a separate maintenance operation. Possession-boundary or
window-metadata changes require rebuilt, verified index candidates before promotion.
Production uses Qdrant Cloud Inference with the configured 384-dimensional MiniLM
model; the API image contains no PyTorch or local model weights. Postgres remains
the authoritative source and can rebuild every collection.

## Safety and operations

- Readiness requires Postgres and a validated active release; optional
  dependencies are reported but do not fail readiness.
- Anonymous clients are protected by per-minute and per-day limits using a
  daily HMAC of the resolved client address.
- API responses include request IDs and hardened security headers.
- Sentry scrubbing removes request data, headers, cookies, environment, user
  data, prompt text, and breadcrumb details; replay is disabled.
- Migrations are expand-only so the previous image and release remain available
  for rollback.
- Rollout records persist attempted components before external I/O, so interrupted
  or uncertain publication retains the restoration scope.

Operational procedures and launch gates live in
`docs/production-runbook.md` and `docs/release-checklist.md`.
