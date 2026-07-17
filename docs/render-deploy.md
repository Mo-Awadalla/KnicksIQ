# Render deployment

KnicksIQ ships from the root `render.yaml` blueprint as a manually promoted,
immutable archive.

## Services

- `knicksiq-api`: Dockerized FastAPI read service.
- `knicksiq-web`: static Vite frontend.
- `knicksiq-redis`: ephemeral Render Free Key Value runtime state.
- Neon Free Postgres: external authoritative store supplied through `DB_URL`.

Qdrant is disabled for the free beta. Redis, OpenRouter, and Sentry are
optional at request time: deterministic Postgres-backed answers remain
available when they fail. The free Key Value instance is intentionally
non-persistent because every stored rate-limit, cache, and budget entry is
reconstructible runtime state.

## Before creating the blueprint

1. Complete every owner gate in `docs/release-checklist.md`.
2. Confirm the `knicksiq.win` DNS values, Formspree endpoint, and Nemotron
   allowlist in the blueprint and public files.
3. Create a Neon Free project. In Render, set `DB_URL` to Neon's direct
   connection string and set the optional OpenRouter and Sentry values.
4. Free Render services do not support pre-deploy commands. Run migrations
   against Neon from the local release environment before deploying:

   ```bash
   DB_URL="$NEON_DIRECT_CONNECTION_STRING" uv run alembic upgrade head
   ```

5. Build, validate, and manually approve the immutable release bundle.
6. Build and scan the exact API image that will be promoted.

## Deployment and activation

1. Create the Render blueprint from `render.yaml`. Automatic deploys are
   intentionally disabled.
2. Confirm the local Neon migration completed. Application startup never
   creates tables, runs migrations, seeds data, ingests games, or generates
   reports.
3. Load the validated bundle with `knicksiq-load-release <bundle> --sha256
   <sha>`. Stage it first; do not activate it until the image and deterministic
   retrieval checks have passed.
4. Activate the Postgres release. Qdrant indexing is deferred while the free
   beta uses deterministic Postgres/lexical retrieval.
5. Manually deploy the immutable API and web artifacts.
6. Render uses `GET /health/live` for deploy health checks so the first deploy
   can complete before release data is loaded. Before go-live, require
   `GET /health/ready` to return
   200 with the expected data version. Run one archive and one deterministic
analyst synthetic before go-live.

When migrating an existing Blueprint, Render does not delete the old managed
Postgres instance or replace an existing `sync: false` value automatically.
Set `DB_URL` to the Neon direct connection string in the API dashboard, then
delete the old `knicksiq-postgres` resource and downgrade `knicksiq-api` to Free
to stop paid compute charges.

Production exposes only the public read endpoints and `POST /analysis/query`.
Swagger, ingestion, job, report-generation, deletion, and run-detection routes
are excluded from the production router. The worker and MCP packages remain
offline/development tools and are not Render services.

See `docs/production-runbook.md` for rollback, restore, dependency-outage,
monitoring, and secret-rotation procedures.
