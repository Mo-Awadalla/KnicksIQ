# Local staged RAG index

Use this path to build a small local Qdrant possession index before attempting a
full season.

Start the local dependencies and API:

```sh
docker compose up -d postgres qdrant api
```

Build a fresh possession collection for the 10 most recent cached Knicks games:

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
  --game-order recent \
  --reset-qdrant
```

The release build creates immutable physical collections for game summaries,
box-score facts, reviewed reports, and possessions. It validates every point
count before promoting all stable aliases in one operation. Each collection
also receives payload indexes for every supported release/date/team/player/
period filter, which Qdrant Cloud requires for filtered queries. Possession
summaries are deterministic and provider-free; this command never calls
OpenRouter.

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
  --out-dir /tmp/knicksiq-rag-index \
  --reset-qdrant
```

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
