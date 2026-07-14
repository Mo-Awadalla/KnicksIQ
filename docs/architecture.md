# KnicksIQ architecture

## Production system

KnicksIQ serves one immutable Knicks 2025–26 archive. Render hosts a static
React application, a read-only FastAPI service, and managed Postgres. Qdrant
Cloud adds semantic retrieval; Upstash Redis adds distributed rate limits,
answer caching, circuit state, and AI budget counters; OpenRouter may phrase
facts that KnicksIQ has already computed. Sentry receives scrubbed errors and
low-sample traces.

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
API does not run migrations or mutate archive data at startup; Render runs the
expand-only Alembic migration separately before deployment.

## Runtime request flow

The web application calls the public API anonymously. Archive endpoints read
the active release directly from Postgres. `POST /analysis/query` classifies the
question, refuses unsupported/live/tactical requests, and computes canonical
facts from Postgres. Semantic retrieval can add possession and report evidence
from release-versioned Qdrant collections. OpenRouter is allowed only to phrase
already-computed evidence and is constrained by an allowlist and budget cutoff.
Every supported factual claim carries a source citation and data version.

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

Teams and players supply entity metadata. Documents/chunks support local and
legacy retrieval paths. Jobs exist for offline/development workflows only.
See `docs/data-model.md` for field-level detail.

## RAG indexing

The offline indexer creates immutable physical collections for game summaries,
box-score facts, reviewed reports, and possession chunks. It verifies every
point count before moving the stable aliases together. Production uses Qdrant
Cloud Inference, so the API image contains no PyTorch or local model weights.
Postgres/lexical retrieval remains authoritative during a Qdrant outage.

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

Operational procedures and launch gates live in
`docs/production-runbook.md` and `docs/release-checklist.md`.
