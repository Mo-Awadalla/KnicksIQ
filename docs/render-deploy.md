# Render deployment

KnicksIQ ships from the root `render.yaml` blueprint as a manually promoted,
immutable archive.

## Services

- `knicksiq-api`: Dockerized FastAPI read service.
- `knicksiq-web`: static Vite frontend.
- `knicksiq-redis`: ephemeral Render Free Key Value runtime state.
- Neon Free Postgres: external authoritative store supplied through `DB_URL`.
- Qdrant Cloud: external release-versioned vector store supplied through
  `QDRANT_URL` and `QDRANT_API_KEY`.

Launch goes straight to `llm_primary` with no sampled shadow stage. Qdrant Cloud Inference and
hybrid retrieval are enabled. Qdrant, Redis, OpenRouter, and Sentry remain optional
for availability: deterministic Postgres-backed answers remain available when
they fail. The free Key Value instance is intentionally non-persistent because
every stored rate-limit, cache, and budget entry is reconstructible runtime
state.

## Before creating the blueprint

1. Complete every owner gate in `docs/release-checklist.md`.
2. Confirm the `knicksiq.win` DNS values, Formspree endpoint, and Nemotron
   allowlist in the blueprint and public files.
3. Create a Neon Free project and Qdrant Cloud cluster. In Render, set `DB_URL`
   to Neon's direct connection string and set `QDRANT_URL`, `QDRANT_API_KEY`,
   OpenRouter, and Sentry secrets. Never store those values in the blueprint.
   For an existing Blueprint service, open `knicksiq-api` → **Environment**,
   enter the values in the existing `QDRANT_URL` and `QDRANT_API_KEY` rows,
   then choose **Save and deploy**. A `sync: false` Blueprint entry is only a
   secret placeholder; syncing the Blueprint does not populate its value.
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
4. Prepare Qdrant from the validated staged release in an authorized isolated
   database using `knicksiq-build-rag-index --season 2025-26 --data-version <version>`.
   Resolve the exact four physical collection destinations and existing account/
   project quota before writes. The versioned path is create-only, preflights all
   four targets and aliases before writing, and never promotes aliases.
   Complete identity-matching candidates are reused without embedding/upsert
   calls. Conflicting, partial or already-aliased targets fail closed; never use
   `--reset-qdrant` or delete retained collections to force a rebuild.
   Validate hosted counts, dimensions, source/payload/embedding identities, server
   payload indexes, release filters and Recall@5 before promoting aliases under
   the separate hash-bound production authorization. Account for billed cloud
   embeddings within the approved provider budget.
5. Complete pre-promotion readiness and obtain separate hash-bound owner
   authorization before any deployment, content activation or alias promotion.
6. Use the verified coordinator below to deploy the exact tested API and web
   commits with `llm_primary` as the final serving mode, then optionally activate
   the previously validated matching Postgres release and candidate Qdrant aliases.
7. Render uses `GET /health/live` for deploy health checks so the first deploy
   can complete before release data is loaded. Before go-live, require
   `GET /health/ready` to return
   200 with the expected data version. Run the approved archive and analyst served
   acceptance checks; any model calls require an explicitly accounted authorized
   budget. The primary-quality gates must pass before promotion; launch goes
   straight to `llm_primary` with no shadow stage (owner decision, 2026-10-20).

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

## Verified parity release workflow

Current eligibility lives in [the release record](release-evidence/release-record.json),
not historical deployment claims. `Manual verified release` is workflow_dispatch-only.
Configure the `production-owner-approved` GitHub environment with required owner reviewers.
Its `RELEASE_OWNER_APPROVAL_SHA256` secret must equal the reviewed record's SHA-256; the
workflow cannot manufacture this approval. Configure existing Render service IDs/URLs in
`services.api` and `services.web` in that record, plus environment credentials.

Keep code and evidence commits distinct: the workflow checks out the selected tested code
commit under `tested/` and the workflow's evidence commit under `evidence/`. This avoids
asking a record committed inside Git to contain its own commit hash. Every passing check
must reference the tested code commit and a hashed artifact in the evidence checkout.

The coordinator sends Render the exact tested `commitId`, records both returned deployment
IDs, verifies the deployed commits, then optionally promotes a previously validated staged
dataset and evaluated candidate aliases. Its preflight rejects stale rollback snapshots and
automatic deploys. Failures trigger restoration of each attempted component and produce
workflow failure annotations; configure owner notifications for failed workflow runs.
Never continue after `restoration_failed` without owner incident handling.

Render rebuilds from Git, so artifact identity with CI is not asserted. API references:
[trigger deploy](https://api-docs.render.com/reference/create-deploy) and
[rollback](https://api-docs.render.com/reference/rollback-deploy).

## Free-plan keepalive and launch settings

The owner chose Render Free with an external ping. `.github/workflows/api-keepalive.yml`
requests `/health/live` every ten minutes, away from the start of the hour. It has no
repository permissions or secrets, performs no model calls, and fails on an HTTP error,
an invalid response, or a 90-second timeout. It can also be dispatched manually.

GitHub runs scheduled workflows only from the default branch. This schedule activates
only after this workflow is merged to that branch.

This is best-effort wakeup traffic, not an availability guarantee. GitHub can delay or
drop scheduled jobs and disables public-repository schedules after 60 days without
repository activity. See [GitHub's schedule limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
Watch workflow failures and retain the separate readiness and served-answer checks.

Only during the explicitly authorized deployment, set
`OPENROUTER_MONTHLY_CUTOFF_USD=20` on the API service. The blueprint's current value
remains `2` until that deployment change; do not sync it over the approved live setting.
Do not change the plan or production environment as part of evidence preparation.

After deployment, measure the hosted analyst. The owner will upgrade the API plan if
p95 is at least 15 seconds, the error rate is at least 1%, or the first request after
an idle period fails during a cold start. Local checks and keepalive success do not
replace this hosted check.
