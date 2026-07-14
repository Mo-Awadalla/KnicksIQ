# KnicksIQ

KnicksIQ is an anonymous, unofficial archive for the Knicks’ 2025–26 regular season and
postseason. It answers supported factual questions from immutable game, play-by-play, period,
team, and player data with claim-level citations. Unsupported tactical or out-of-archive claims
are declined rather than invented.

## Production shape

- `apps/web`: anonymous React archive and analyst experience.
- `apps/api`: read-only production FastAPI service.
- Neon Free Postgres: authoritative factual data and active release metadata.
- Qdrant and Redis are disabled for the free beta; Postgres/lexical retrieval and in-process
  safety controls remain available.
- OpenRouter: optional phrasing of already-computed facts.
- Sentry: scrubbed exception, trace, alert, and uptime monitoring.

Workers, ingestion, report generation, MCP, admin routes, Swagger, and runtime data mutations are
not part of the production deployment. NBA ingestion and release construction are offline tools.

## Current release candidate

The recovered 2025–26 candidate is under `release-artifacts/2025-26`:

- 101 canonical games: 82 regular season and 19 postseason.
- 46,500 normalized play-by-play events.
- 202 team box-score rows and 2,748 player box-score rows.
- 816 period-score rows, including overtime recovery from cumulative play-by-play.
- 101 deterministic report drafts and a hash-bound manual review pack.
- Data-only bundle SHA-256: `55d6aa90c206f3b3386cb4b8d056fb84ae51f5482a86e8c2ee920c72378c385c`.

The data-only candidate passes full reconciliation. It is not activatable as the public release
until every report hash is manually approved and the remaining owner launch gates are signed.

## Local development

Start the read stack:

```bash
docker compose up -d postgres redis qdrant api web
```

Useful URLs:

- Web: `http://localhost:8080`
- API liveness: `http://localhost:8000/health/live`
- API readiness: `http://localhost:8000/health/ready`
- API docs in development only: `http://localhost:8000/docs`
- Qdrant: `http://localhost:6333`

Readiness intentionally returns 503 until a validated release is active. API startup never creates
tables, runs migrations, seeds data, ingests games, or generates reports.

## Release recovery workflow

Back up and migrate the cached database first, then fetch only the missing release dimensions:

```bash
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:5432/knicksiq \
uv run alembic upgrade head

DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:5432/knicksiq \
NBA_API_RATE_REMAINING_MINUTES=30 \
uv run --package knicksiq-worker knicksiq-fetch-release-boxes \
  --season 2025-26 \
  --out-dir release-artifacts/2025-26/box-scores

DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:5432/knicksiq \
uv run --package knicksiq-worker knicksiq-export-release \
  --season 2025-26 \
  --version 2025-26.20260714.1 \
  --box-dir release-artifacts/2025-26/box-scores \
  --review-manifest release-artifacts/2025-26/report-approvals.json \
  --output release-artifacts/2025-26/release-candidate.json
```

Generate the review pack and strict production bundle:

```bash
uv run --package knicksiq-worker knicksiq-create-report-review-pack \
  release-artifacts/2025-26/release-candidate.json \
  --markdown release-artifacts/2025-26/reports-review.md \
  --approvals release-artifacts/2025-26/report-approvals.json

uv run --package knicksiq-worker knicksiq-build-release \
  release-artifacts/2025-26/release-candidate.json \
  release-artifacts/2025-26/knicksiq-2025-26.json.gz
```

`knicksiq-build-release` rejects unreviewed reports. Candidate-only data validation can explicitly
use `--allow-unreviewed-reports`; such a bundle cannot be loaded or activated by the production
loader.

Load the final bundle transactionally and idempotently:

```bash
DB_URL=postgresql+asyncpg://USER:PASSWORD@HOST/DATABASE \
uv run --package knicksiq-worker knicksiq-load-release \
  release-artifacts/2025-26/knicksiq-2025-26.json.gz \
  --sha256 SHA256_FROM_BUILD \
  --activate
```

## Verification

Backend:

```bash
uv run ruff format --check apps packages migrations
uv run ruff check apps packages migrations
uv run pyright apps packages migrations
uv run pytest
```

Frontend:

```bash
cd apps/web
pnpm lint
pnpm format:check
pnpm build
pnpm test
pnpm e2e
```

Production images:

```bash
docker compose build api web
```

Local embedding and reranking dependencies are an explicit offline extra:

```bash
uv sync --package knicksiq-api --extra local-rag
```

The production API does not include PyTorch or local model weights. See
`docs/production-runbook.md`, `docs/release-checklist.md`, and `docs/evaluation.md` for operational,
quality, recovery, and owner sign-off gates.
