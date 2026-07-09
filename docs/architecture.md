# KnicksIQ Architecture

## High-level system

```
                    +-------------+
                    |  web (React) |
                    |  Vite + TS   |
                    +------+------+
                           |
                       /api/*  (HTTP)
                           |
                           v
+--------------------+      +-------------------+      +-----------+
|     api-service    |      |     postgres      |      |   redis   |
|  FastAPI + asyncpg +<---->+  (games, events,  |      |  (RQ q)   |
|                    |      |   runs, reports)  |      |           |
+--+--------------+--+      +-------------------+      +-----------+
   |              |                      ^
   |              | HTTP                 | enqueue
   |              v                      |
   |       +---------------+    +--------+----+
   |       | worker-service|    |   jobs table |
   |       | RQ + asyncpg  +--->+ (status)    |
   |       +-------+-------+    +-------------+
   |               |
   |               v
   |       +----------------+
   |       | basketball-core|
   |       | (parsers +     |
   |       |  detectors)    |
   |       +----------------+
   |
   |       +---------------+
   +------>|  mcp-service  |
           |  FastMCP      |
           |  (stdio + SSE)|
           +---------------+
```

## Service boundaries

### `api` — FastAPI backend

The read/write HTTP surface. Owns:

- REST endpoints (`/games`, `/players`, `/reports`, `/jobs`, etc.)
- Auth (deferred past Phase 1 per the spec — none yet)
- DB session management
- Pydantic schemas for request/response validation
- The report generator service (orchestrator that calls the LLM adapter)
- Structured logging via `structlog`

It is *stateless*: every request opens a session, runs, and closes it. The
API never holds an open connection to the worker or the LLM provider.

### `worker` — RQ + Redis background workers

Owns:

- `ingest_games` — pull games from the data source, upsert into Postgres
- `ingest_game_detail` — pull play-by-play for one game, normalize, store
- `detect_runs` — run scoring-run + bad-stretch detectors on one game
  and persist results

The worker shares SQLAlchemy models with the API but runs its own
session factory. It writes `Job` rows that the API reads for status.

### `mcp` — Model Context Protocol tool server

A standalone process that uses the official MCP Python SDK to
expose basketball tools. LLM clients (Claude Desktop, Cursor, custom
agents) connect to it and call tools like `knicks.get_game` or
`knicks.find_scoring_runs`. The MCP server is **read-only** and
does not own any persistent state — it reads from the same Postgres
the API writes to.

The MCP server logs every tool call (name, params, latency, status)
so the dashboard's tool-trace viewer can show what the LLM did.

### `web` — React + TypeScript dashboard

A Vite-served SPA. Talks to the API over HTTP (proxied in dev). Uses
TanStack Query for caching and React Router for navigation.

### `postgres` — Primary store

Stores everything persistent: teams, players, games, events,
pre-computed runs, pre-computed bad stretches, reports, documents,
chunks, jobs, audit logs.

### `redis` — Job queue + cache

Used by RQ for the work queue. The API never reads from Redis
directly — it always reads the `jobs` table, which is the durable
record of work.

## Data flow: generating a Postgame Autopsy

1. User clicks "Generate Postgame Autopsy" on the game detail page.
2. The frontend POSTs `/reports/postgame { game_id: 1 }`.
3. The API's report generator service runs **synchronously**:
   a. `fetch_game` — read the game row.
   b. `fetch_scoring_runs` — read pre-computed runs from `scoring_runs`.
   c. `fetch_bad_stretches` — read pre-computed bad stretches.
   d. `fetch_event_snippets` — sample 6 made-shot/turnover events.
   e. Build a context object containing the structured data.
   f. `llm_generate` — call `MockLLMAdapter.generate(system, user)`.
      The mock uses templated logic to produce a JSON report whose
      `turning_point` and `best_stretch` are grounded in the real
      scoring runs.
   g. Validate the report's structure.
   h. Persist a `reports` row with `sources_json` and `tool_trace_json`.
4. Return the report (including tool trace) to the client.
5. The frontend navigates to `/reports/{id}` to display it.

## Data flow: detecting scoring runs

1. User clicks "Detect Runs" (or `POST /games/{id}/detect-runs`).
2. The API enqueues an RQ job and creates a `Job` row (status=queued).
3. The worker picks up the job, marks it `started`.
4. The worker loads all `game_events` for the game, converts them to
   the basketball-core domain `GameEvent` model, and runs
   `detect_scoring_runs` and `detect_bad_stretches`.
5. The worker deletes any existing rows for this game, then inserts
   the new `scoring_runs` and `bad_stretches`.
6. The worker marks the job `finished` and writes the result summary.
7. The API's next `GET /games/{id}/runs` returns the new rows.

## Database schema (high level)

```
teams (id, name, ...)
  |
  +-- players (id, full_name, team_id, position, ...)
  |
  +-- games (id, nba_game_id, home_team_id, away_team_id, home_score, away_score, ...)
        |
        +-- game_events (id, game_id, sequence, period, clock, team_id, event_type, ...)
        |
        +-- scoring_runs (id, game_id, team_id, period, start_clock, end_clock, ...)
        |
        +-- bad_stretches (id, game_id, period, start_clock, end_clock, summary, ...)
        |
        +-- reports (id, game_id, title, summary, turning_point, ..., tool_trace_json)
        |
        +-- documents (id, source_type, game_id, body, ...)
              +-- chunks (id, document_id, text, embedding_json, metadata_json)

jobs (id, job_type, status, payload_json, result_json, error_message, ...)
```

## Observability

- **Structured JSON logs** via `structlog` in the API. In dev
  (`DEBUG=true`) logs are pretty-printed to the console.
- **Request IDs** propagate through the call chain.
- **Job status** is durable in the `jobs` table — the API can serve
  `GET /jobs/{id}` even after a worker restart.
- **Tool-call logs** are written into each `reports.tool_trace_json`,
  recording every internal tool the report generator invoked
  (fetch_game, fetch_scoring_runs, etc.) along with its latency.

## Why these choices

- **uv for monorepo**: fast, lockfile-driven, no PDM/Poetry complexity.
- **SQLite for tests**: zero infra to run the test suite; production
  uses Postgres. Both share the same SQLAlchemy models.
- **RQ over Celery**: simpler, fewer dependencies, sufficient for
  this scale. RQ's web UI is a nice bonus.
- **Official MCP Python SDK**: standard, well-supported, and works
  out-of-the-box with Claude Desktop and other MCP clients.
- **Mock LLM adapter**: lets the system run end-to-end without
  external API keys. Swap in OpenAI/Anthropic by subclassing
  `LLMAdapter`.
- **Static seed data**: deterministic dev experience; no flaky
  tests waiting on a remote API.

## What's deferred (intentionally)

- **Real LLM integration**: the report generator ships with a mock
  adapter. To wire a real LLM, subclass `LLMAdapter` and inject it
  into `generate_postgame_report`.
- **pgvector embeddings + cosine retrieval**: the `chunks` table is
  in place with an `embedding_json` column. Real embedding generation
  and vector search are Phase 8+ work.
- **Authentication**: per the spec, this is deferred past Phase 1.
- **Live `nba_api` integration** *(shipped — see Phase 8 below)*: a
  live `NbaApiDataSource` now sits alongside `StaticSeedDataSource`
  and is selected via `NBA_DATA_SOURCE=nba_api`.
- **Tool-call persistence to the `tool_calls` table**: currently
  the report's tool trace lives in `reports.tool_trace_json`. A
  dedicated `tool_calls` table is a small follow-up.

## Phase 8: live NBA data source

The worker can now fetch live data from `stats.nba.com` via
[swar/nba_api](https://github.com/swar/nba_api) instead of reading
the static seed JSON. Source selection is env-driven — no code
change required to switch.

### Data source factory

`worker_app.adapters.get_data_source(settings, seed_dir)` returns
the active implementation:

| Env var `NBA_DATA_SOURCE` | Returns             | Used for           |
|---------------------------|---------------------|--------------------|
| `static` *(default)*      | `StaticSeedDataSource` | dev, tests, CI  |
| `nba_api`                 | `NbaApiDataSource`    | prod, backfill   |

Both satisfy the same `NBADataSource` protocol (`list_seasons`,
`list_games(season)`, `get_game(nba_game_id)`), so jobs don't care
which is active.

### Live adapter (`NbaApiDataSource`)

- **Endpoints used**:
  - `leaguegamefinder.LeagueGameFinder` (Knicks filter) for season
    listings.
  - `playbyplayv3.PlayByPlayV3` for game detail. The v2 endpoint
    is deprecated as of 2024-25 and returns empty JSON.
  - `commonallplayers.CommonAllPlayers` (active roster only) for
    player backfill.
- **Knicks-only scope**: hardcoded to Knicks games via the team-id
  mapping loaded from `seed/teams.json` at construction. Opponent
  rosters are still pulled by `seed_players_from_nba_api`.
- **ID translation**: the adapter is I/O-only. It returns:
  - `team_id` as a trigraph (read directly from `teamTricode`).
  - `player_id` as the public `nba_player_id` (int). The job is
    responsible for remapping to the internal `players.id` via a
    one-shot `SELECT` before insert.
- **Rate limit**: sliding-window 10 calls/min (configurable via
  `NBA_API_RATE_REMAINING_MINUTES`). The library's own rate-limit
  feature was removed in v1.11.4, so we implement it ourselves.
- **Retry**: inline, 3 attempts with 2s/4s/8s exponential backoff.
  Transient errors (5xx, 429, network) are retried; non-JSON
  parse errors (which often hide a 4xx) are also retried since
  nba_api doesn't call `raise_for_status()`.

### Player ingest job

A new `seed_players_from_nba_api` job calls `commonallplayers` and
upserts the current NBA roster into the `players` table. Run it
once before the first `ingest_games` against the live source, or
whenever the league's active roster changes significantly (trades
mid-season will be picked up on the next run).

Note: position and jersey_number are NOT populated by this job
(`commonallplayers` doesn't expose them). Backfilling requires
~600 per-player `commonplayerinfo` calls (~1h at our rate limit)
and is deferred.

### Environment variables (`.env.example`)

```
NBA_DATA_SOURCE=static
NBA_API_SEASONS=2021-22,2022-23,2023-24,2024-25,2025-26
NBA_API_TIMEOUT_SECONDS=30
NBA_API_PROXY=
NBA_API_RATE_REMAINING_MINUTES=10
NBA_API_USER_AGENT=KnicksIQ/0.1 (sports analytics)
NBA_API_RETRY_ATTEMPTS=3
NBA_API_RETRY_BACKOFF_SECONDS=2.0
```

### Parser refactor follow-up

The adapter normalizes nba_api's v3 shape into the seed's event
dict shape inline. A future refactor of
`packages/basketball-core/src/basketball_core/parsers/play_by_play.py`
to accept the v3 shape natively would let us delete the
normalization block in `_parse_pbp_v3_action` and the
`get_game` row→dict reconstruction.

**TODO(file-issue):** file a tracking issue for the parser
refactor. The adapter's module docstring carries the same TODO.
