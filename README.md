# KnicksIQ

KnicksIQ is an anonymous, unofficial archive for the Knicks’ 2025–26 regular season and
postseason. It answers supported factual questions from immutable game, play-by-play, period,
team, and player data with claim-level citations. Unsupported tactical or out-of-archive claims
are declined rather than invented.

## Production shape

- `apps/web`: anonymous React archive and analyst experience.
- `apps/api`: read-only production FastAPI service.
- Neon Free Postgres: authoritative factual data and active release metadata.
- Render Free Key Value: ephemeral shared rate limits, response caching, and AI budget state.
- Qdrant Cloud provides optional hybrid retrieval; Postgres/lexical retrieval remains authoritative when it is unavailable.
- OpenCode Go, the owner's subscription, is the model host. `deepseek-v4.1-flash` writes over
  Chat Completions and `gpt-6-luna` reviews over the Responses API. Both compose answers from
  backend-computed claims; deterministic cited facts remain the fallback. The owner accepted the
  terms risk described in [the architecture note](docs/architecture.md#production-system).
- Sentry: scrubbed exception, trace, alert, and uptime monitoring.

Workers, ingestion, report generation, MCP, admin routes, Swagger, and runtime data mutations are
not part of the production deployment. NBA ingestion and release construction are offline tools.

## Analyst

The default answer path is the bounded evidence loop described in
[docs/analyst-evidence-loop.md](docs/analyst-evidence-loop.md). Nine tools are registered:
`get_player_stats`, `get_team_stats`, `compare_windows`, `discover_facts`, `search_archive`,
`get_evidence`, `get_game_flow`, `get_team_splits` and `get_period_scoring`. Quarter,
period, play-by-play and split questions are supported. Season-level records default to the
regular season and the answer states the phase; the overall record appears only when asked.

The backend computes every number as an immutable claim with a receipt. Prompt v4 and validator
v2 add a deterministic number gate before the independent reviewer. `ANALYST_REASONING_EFFORT=none`
is the default, token caps are enforced, and deterministic prefetch (`ANALYST_PREFETCH_ENABLED`)
runs one clear tool before the first model call. Typed pre-model refusals cover instruction
override, wagering and out-of-archive dates; other unsupported wording reaches the analyst, which
declines or explains coverage. `refused=true` marks a decline or coverage explanation, not an
error.

At the $2 cutoff, measured capacity is about 1,009 questions per month on the 70-question mix
and about 750 on the held-out rate. Mean cost is $0.001981 per question on the 70-question mix.
Capacity is route dependent. Measured latency on 140 questions at the 16,000-byte input budget is
p50 3,312 ms and p95 7,640 ms; the four second p95 gate is not met. The final measurement is in
[docs/release-evidence/llm-primary-20261021/final/README.md](docs/release-evidence/llm-primary-20261021/final/README.md).

`apps/web` is the only maintained frontend. The retired frontend remains available
in Git history; historical release evidence is kept unchanged. Install frontend
dependencies from `apps/web/pnpm-lock.yaml`; `node_modules/` is ignored repository-wide.

## Current release candidate

The recovered 2025–26 candidate is under `release-artifacts/2025-26`:

- 101 canonical games: 82 regular season and 19 postseason.
- 46,500 normalized play-by-play events.
- 202 team box-score rows and 2,748 player box-score rows.
- 816 period-score rows, including overtime recovery from cumulative play-by-play.
- 101 deterministic report drafts and a hash-bound manual review pack.
- Data-only bundle SHA-256: `55d6aa90c206f3b3386cb4b8d056fb84ae51f5482a86e8c2ee920c72378c385c`.

Release eligibility is tracked in the [machine-readable release record](docs/release-evidence/release-record.json)
and its [generated review view](docs/release-evidence/release-record.md). Local archive counts
above do not establish active production identity or approval. The replacement report review policy
requires agent verification of every report and owner approval of the template, exceptions and
content-bound audit summary. Unresolved report checks block launch.

## Local development

Enable the repository's pre-commit hook once per clone with `make hooks`.
`make install` also enables it. The hook requires Git and Python 3.10+ and checks
only added, modified, renamed, or type-changed regular files in the index, using
their staged contents. Each authored text file must be at most 5,000 tokens,
calculated as bytes / 4, or 20,000 bytes. Unstaged and unchanged files are ignored.

Lockfiles, generated output, and vendored dependencies are excluded through the
staged `.gitattributes` rules. Binary blobs, symlinks, and submodules are skipped.
For additional machine-generated output, add a narrowly scoped
`linguist-generated=true` rule and stage it alongside the output. Authored text is
checked regardless of whether an agent or a human wrote it.

If a commit is blocked, split code into cohesive sibling modules and documents by
topic, update imports or links, and keep every resulting file within the limit.
Run the relevant E2E checks, stage the split files with `git add`, and retry.
To verify the hook with real commits in temporary repositories, run
`python3 tools/hooks/e2e.py`. Repeatable results and rejection messages are saved
to `release-artifacts/hooks/e2e.json`.

Audit all existing authored files, including untracked source, with
`python3 tools/hooks/inventory.py release-artifacts/hooks/inventory.json`.
This uses worktree contents and attributes, reports each file above the same
20,000-byte limit, and exits unsuccessfully if any remain.

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
TEST_MODE=true uv run pytest apps packages tools/report_audit
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
