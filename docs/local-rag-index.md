# Local staged RAG index

Use this path to build a small local Qdrant possession index before attempting a
full season.

Start the local dependencies and API:

```sh
docker compose up -d postgres qdrant api
```

Build inactive physical collections for the 10 most recent games of a validated release:

```sh
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:5432/knicksiq \
QDRANT_HOST=localhost \
QDRANT_PORT=6333 \
RAG_QDRANT_ENABLED=true \
RAG_EMBEDDING_DEVICE=cpu \
OPENROUTER_API_KEY= \
uv run --package knicksiq-worker knicksiq-build-rag-index \
  --season 2025-26 \
  --data-version RELEASE_VERSION \
  --out-dir rag-artifacts \
  --game-limit 10 \
  --game-order recent
```

The release build prepares immutable physical collections for game summaries,
box-score facts, reviewed reports, and possessions. It preflights all four targets
and live aliases before any remote write. Complete candidates are reused only
when every source ID, payload, release, dense-vector schema, required payload
index, and stored embedding model/mode/document identity matches; reuse makes no
embedding or upsert calls. Conflicting or partial resources fail without changing
any existing target. Missing collections are created, never reset or deleted.
Aliases are **not** promoted by indexing.

Each collection receives payload indexes for every supported release/date/team/
player/period filter, required by Qdrant Cloud. Embedded Qdrant cannot establish
server-index enforcement and does not satisfy hosted reuse/readiness verification.
`--reset-qdrant` is rejected with `--data-version`; it remains available only for
explicitly disposable, unversioned local indexes. Keep immutable rollback
collections and active aliases intact. For a changed source or embedding identity,
use a separately approved release version, not a destructive rebuild.

Possession summaries are deterministic and provider-free; indexing never calls
OpenRouter. Embeddings may still be billed when cloud inference is enabled.

`RAG_EMBEDDING_DEVICE=cpu` is a useful override on Apple Silicon when MPS is
slower for this compact model. An optional paid deployment can use Qdrant Cloud Inference instead of
shipping local model weights.

For Qdrant Cloud Inference, use the configured cloud URL/key and allow a longer
indexing timeout than the request-time API default:

```sh
QDRANT_TIMEOUT_SECONDS=120 \
RAG_QDRANT_CLOUD_INFERENCE=true \
RAG_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
uv run --package knicksiq-worker knicksiq-build-rag-index \
  --season 2025-26 \
  --data-version RELEASE_VERSION \
  --out-dir /tmp/knicksiq-rag-index
```

Use only an authorized isolated database and exact candidate collection allowlist.
Verify account/project identities and available provisioned quota before writes.
Cloud embeddings require separate counted spending admission; do not enable this
example to bypass a provider budget gate. A failed/partial upload leaves resources
intact and blocks reuse; do not clear them to force a pass.

After indexing, restart the local API if it was already running:

```sh
docker compose up -d api
```

Useful checks:

```sh
curl -sS http://localhost:8000/health/rag
curl -sS http://localhost:6333/collections/knicks_possessions
```

## Full demo cache

For a demo shipment, use the stricter season-cache workflow instead of the
staged 10-game index:

```sh
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:5432/knicksiq \
NBA_DATA_SOURCE=nba_api \
NBA_API_TIMEOUT_SECONDS=90 \
NBA_API_RETRY_ATTEMPTS=2 \
NBA_API_RETRY_BACKOFF_SECONDS=1 \
uv run --package knicksiq-worker knicksiq-cache-season \
  --team NYK \
  --season 2025-26 \
  --include-playoffs \
  --demo-ready \
  --rag-out-dir rag-artifacts
```

The command is DB-first: already cached games are reused, and missing summaries
or play-by-play are backfilled from `nba_api`. It then runs the derived analysis
and rebuilds RAG artifacts for the full cached Knicks season. A non-zero exit
means at least one game is not demo-ready; inspect the printed `failed_games`
and status counts before retrying.
