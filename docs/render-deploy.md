# Render deployment

KnicksIQ ships from the root `render.yaml` blueprint as a manually promoted,
immutable archive.

## Services

- `knicksiq-api`: Dockerized FastAPI read service.
- `knicksiq-web`: static Vite frontend.
- `knicksiq-postgres`: managed Postgres 16 authoritative store.

Qdrant Cloud, Upstash Redis, OpenRouter, and Sentry are configured as external
services. They are optional at request time: deterministic Postgres-backed
answers remain available when they fail.

## Before creating the blueprint

1. Complete every owner gate in `docs/release-checklist.md`.
2. Confirm the `knicksiq.win` DNS values, Formspree endpoint, and Nemotron
   allowlist in the blueprint and public files.
3. Set the unsynced Qdrant, Redis, OpenRouter, and Sentry secrets in Render.
4. Build, validate, and manually approve the immutable release bundle.
5. Build and scan the exact API image that will be promoted.

## Deployment and activation

1. Create the Render blueprint from `render.yaml`. Automatic deploys are
   intentionally disabled.
2. The API pre-deploy command runs `alembic upgrade head`; application startup
   never creates tables, seeds data, ingests games, or generates reports.
3. Load the validated bundle with `knicksiq-load-release <bundle> --sha256
   <sha>`. Stage it first; do not activate it until the image and Qdrant index
   have passed their checks.
4. Build versioned Qdrant collections from the staged Postgres release and
   validate their point counts and Recall@5.
5. Activate the Postgres release and promote the matching Qdrant aliases.
6. Manually deploy the immutable API and web artifacts.
7. Render uses `GET /health/live` for deploy health checks so the first deploy
   can complete before release data is loaded. Before go-live, require
   `GET /health/ready` to return
   200 with the expected data version. Run one archive and one deterministic
   analyst synthetic before go-live.

Production exposes only the public read endpoints and `POST /analysis/query`.
Swagger, ingestion, job, report-generation, deletion, and run-detection routes
are excluded from the production router. The worker and MCP packages remain
offline/development tools and are not Render services.

See `docs/production-runbook.md` for rollback, restore, dependency-outage,
monitoring, and secret-rotation procedures.
