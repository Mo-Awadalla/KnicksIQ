# Graph Report - .  (2026-07-01)

## Corpus Check
- Corpus is ~29,830 words - fits in a single context window. You may not need a graph.

## Summary
- 824 nodes · 1486 edges · 46 communities (27 shown, 19 thin omitted)
- Extraction: 73% EXTRACTED · 27% INFERRED · 0% AMBIGUOUS · INFERRED: 404 edges (avg confidence: 0.58)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_LLM Analyst Query|LLM Analyst Query]]
- [[_COMMUNITY_NBA API Live Adapter|NBA API Live Adapter]]
- [[_COMMUNITY_Bad Stretch Detector|Bad Stretch Detector]]
- [[_COMMUNITY_Detect Runs Worker|Detect Runs Worker]]
- [[_COMMUNITY_Health & Router|Health & Router]]
- [[_COMMUNITY_MCP Tool Logging|MCP Tool Logging]]
- [[_COMMUNITY_Docker Architecture|Docker Architecture]]
- [[_COMMUNITY_Web API Client|Web API Client]]
- [[_COMMUNITY_Players Endpoints|Players Endpoints]]
- [[_COMMUNITY_Jobs Endpoints|Jobs Endpoints]]
- [[_COMMUNITY_Reports Endpoints|Reports Endpoints]]
- [[_COMMUNITY_Data Source Adapters|Data Source Adapters]]
- [[_COMMUNITY_Scoring Run Detector|Scoring Run Detector]]
- [[_COMMUNITY_Web Dependencies|Web Dependencies]]
- [[_COMMUNITY_LLM Adapter|LLM Adapter]]
- [[_COMMUNITY_TypeScript Config|TypeScript Config]]
- [[_COMMUNITY_Games API Tests|Games API Tests]]
- [[_COMMUNITY_App Settings|App Settings]]
- [[_COMMUNITY_Reports API Tests|Reports API Tests]]
- [[_COMMUNITY_NBA Stats Endpoints|NBA Stats Endpoints]]
- [[_COMMUNITY_Jobs API Tests|Jobs API Tests]]
- [[_COMMUNITY_Players API Tests|Players API Tests]]
- [[_COMMUNITY_Database Session|Database Session]]
- [[_COMMUNITY_Analysis API Tests|Analysis API Tests]]
- [[_COMMUNITY_Worker Entry Point|Worker Entry Point]]
- [[_COMMUNITY_Vite Environment Types|Vite Environment Types]]
- [[_COMMUNITY_Containerized Postgres|Containerized Postgres]]
- [[_COMMUNITY_Redis Cache|Redis Cache]]
- [[_COMMUNITY_API Container Config|API Container Config]]
- [[_COMMUNITY_Docker Compose Override|Docker Compose Override]]
- [[_COMMUNITY_Knicks Analysis Query|Knicks Analysis Query]]
- [[_COMMUNITY_Concept Reasoning|Concept Reasoning]]
- [[_COMMUNITY_Job Dispatch Concept|Job Dispatch Concept]]
- [[_COMMUNITY_API Models|API Models]]
- [[_COMMUNITY_MCP Tooling|MCP Tooling]]
- [[_COMMUNITY_LLM Citations|LLM Citations]]
- [[_COMMUNITY_Postgres Connection|Postgres Connection]]
- [[_COMMUNITY_API Test Patterns|API Test Patterns]]
- [[_COMMUNITY_Postgres Init|Postgres Init]]
- [[_COMMUNITY_Dev Postgres Init|Dev Postgres Init]]
- [[_COMMUNITY_CI Workflow|CI Workflow]]
- [[_COMMUNITY_Web API Root|Web API Root]]

## God Nodes (most connected - your core abstractions)
1. `Game` - 45 edges
2. `GameEvent` - 39 edges
3. `GameEvent` - 35 edges
4. `NbaApiDataSource` - 27 edges
5. `BadStretch` - 25 edges
6. `ScoringRun` - 25 edges
7. `JobAcceptedResponse` - 17 edges
8. `generate_postgame_report()` - 17 edges
9. `compilerOptions` - 16 edges
10. `Base` - 15 edges

## Surprising Connections (you probably didn't know these)
- `get_runs()` --calls--> `detect_scoring_runs()`  [INFERRED]
  apps/api/app/api/games.py → packages/basketball-core/src/basketball_core/detectors/scoring_run.py
- `get_bad_stretches()` --calls--> `detect_bad_stretches()`  [INFERRED]
  apps/api/app/api/games.py → packages/basketball-core/src/basketball_core/detectors/bad_stretch.py
- `AsyncSession` --uses--> `Game`  [INFERRED]
  apps/api/app/core/seed_loader.py → packages/basketball-core/src/basketball_core/models/game.py
- `seed_games()` --calls--> `parse_events()`  [INFERRED]
  apps/api/app/core/seed_loader.py → packages/basketball-core/src/basketball_core/parsers/play_by_play.py
- `SearchResult` --uses--> `Game`  [INFERRED]
  apps/api/app/services/rag.py → packages/basketball-core/src/basketball_core/models/game.py

## Import Cycles
- 1-file cycle: `apps/api/app/main.py -> apps/api/app/main.py`

## Hyperedges (group relationships)
- **MCP Tool Suite (Read-Only Basketball Tools)** — docs_mcp_tools_knicks_get_games, docs_mcp_tools_knicks_get_game, docs_mcp_tools_knicks_get_box_score, docs_mcp_tools_knicks_get_play_by_play, docs_mcp_tools_knicks_find_scoring_runs, docs_mcp_tools_knicks_find_bad_stretches [EXTRACTED 1.00]
- **KnicksIQ Service Topology (Docker Compose)** — docker_compose_postgres, docker_compose_redis, docker_compose_api, docker_compose_worker, docker_compose_mcp, docker_compose_web [EXTRACTED 1.00]
- **RAG Layer (Deferred to Phase 8+)** — docs_data_model_documents_table, docs_data_model_chunks_table [EXTRACTED 1.00]

## Communities (46 total, 19 thin omitted)

### Community 0 - "LLM Analyst Query"
Cohesion: 0.06
Nodes (75): AnalysisCitation, AnalysisQueryRequest, AnalysisQueryResponse, _client_id(), _is_supported_question(), _matching_games(), query_analysis(), _rate_limit() (+67 more)

### Community 1 - "NBA API Live Adapter"
Cohesion: 0.05
Nodes (53): NbaApiDataSource, Live NBA.com data source backed by `swar/nba_api`.  This module is a pure I/O ad, Return seed-shaped game dicts for Knicks games in `season`.          Each entry:, Return a seed-shaped game dict with `events` populated., Return current-season players from `commonallplayers`., Return `commonplayerinfo` row for `nba_player_id`, or None., Return extra headers (e.g. User-Agent) for the nba_api call, or None., Call `fn` with rate limiting and transient-error retry.          Transient error (+45 more)

### Community 2 - "Bad Stretch Detector"
Cohesion: 0.06
Nodes (57): BadStretch, BadStretchConfig, _build_window_events(), _clock_to_seconds(), detect_bad_stretches(), _last_made_fg_seconds(), Bad stretch detector.  A "bad stretch" is a contiguous window of play where the, Parse a 'M:SS' clock string into the remaining seconds in the period. (+49 more)

### Community 3 - "Detect Runs Worker"
Cohesion: 0.05
Nodes (52): Any, Any, AsyncSession, Job, Any, Path, _delete_existing(), detect_game_features() (+44 more)

### Community 4 - "Health & Router"
Cohesion: 0.06
Nodes (41): Health check endpoints., Aggregate router for the API., API auth dependencies., Protect mutation/admin endpoints with a shared API key.      Development and tes, require_admin_api_key(), get_team(), list_teams(), Team-related endpoints. (+33 more)

### Community 5 - "MCP Tool Logging"
Cohesion: 0.07
Nodes (44): Any, Any, Game, FastMCP, Tool-call logging.  The MCP server logs every tool invocation to the `tool_calls, Context manager that logs a tool call's start, end, and duration., tool_call(), BadStretchModel (+36 more)

### Community 6 - "Docker Architecture"
Cohesion: 0.07
Nodes (48): API Service Container, MCP Service Container, Postgres Service Container, Redis Service Container, Web Service Container, Worker Service Container, /games Endpoints, GET /health (Liveness Probe) (+40 more)

### Community 7 - "Web API Client"
Cohesion: 0.07
Nodes (27): api, askAnalyst(), fetchBadStretches(), fetchGame(), fetchGames(), fetchPlayByPlay(), fetchReport(), fetchRuns() (+19 more)

### Community 8 - "Players Endpoints"
Cohesion: 0.08
Nodes (33): get_player(), list_players(), Player-related endpoints., AsyncSession, Depends, get_db, Any, Game (+25 more)

### Community 9 - "Jobs Endpoints"
Cohesion: 0.09
Nodes (31): Enqueue a job to (re)compute scoring runs and bad stretches for a game.      Onc, trigger_detect_runs(), _create_job_row(), get_job_status(), IngestGameDetailRequest, IngestGamesRequest, JobStatusResponse, Job management endpoints.  Enqueue work and read job status. The queue uses RQ + (+23 more)

### Community 10 - "Reports Endpoints"
Cohesion: 0.11
Nodes (28): delete_report(), generate_postgame(), get_report(), list_reports(), PostgameRequest, PostgameResponse, Synchronously generate a postgame report for a game.      In a heavier setup thi, ReportSummary (+20 more)

### Community 11 - "Data Source Adapters"
Cohesion: 0.12
Nodes (16): get_data_source(), NBADataSource, parse_game_date(), Data source adapters.  The `NBADataSource` protocol defines a stable interface f, Protocol for NBA data sources. Implementations may be remote or local., Reads game data from the API's seed JSON files.      This is the default source., Construct the data source selected by `settings.data_source`.      Args:, StaticSeedDataSource (+8 more)

### Community 12 - "Scoring Run Detector"
Cohesion: 0.13
Nodes (26): detect_knicks_runs(), detect_opponent_runs(), detect_scoring_runs(), Scoring run detector.  A "scoring run" is a stretch of play where one team outsc, Return only the scoring runs credited to the Knicks., Return only the scoring runs credited to the opponent., Detect all scoring runs in a chronological list of events.      A run is a maxim, ScoringRunConfig (+18 more)

### Community 13 - "Web Dependencies"
Cohesion: 0.08
Nodes (24): dependencies, axios, react, react-dom, react-router-dom, @tanstack/react-query, devDependencies, autoprefixer (+16 more)

### Community 14 - "LLM Adapter"
Cohesion: 0.15
Nodes (13): ABC, Any, _build_report(), get_llm_adapter(), LLMAdapter, MockLLMAdapter, OpenAICompatibleLLMAdapter, LLM adapter — abstract base + a deterministic mock.  The mock generates a report (+5 more)

### Community 15 - "TypeScript Config"
Cohesion: 0.11
Nodes (17): compilerOptions, allowImportingTsExtensions, isolatedModules, jsx, lib, module, moduleDetection, moduleResolution (+9 more)

### Community 16 - "Games API Tests"
Cohesion: 0.12
Nodes (5): Tests for game endpoints., Runs are computed from cached events when no persisted rows exist., POST /games/{id}/detect-runs enqueues a detection job., test_detect_runs_endpoint_returns_202(), test_runs_endpoint_computes_from_cached_events()

### Community 17 - "App Settings"
Cohesion: 0.20
Nodes (8): get_settings(), Application configuration loaded from environment variables., Settings, get_settings(), MCP server configuration., Settings, BaseSettings, Application settings.      When `test_mode` is True, the DB URL is forced to an

### Community 18 - "Reports API Tests"
Cohesion: 0.20
Nodes (3): Tests for /reports endpoints., A missing game should surface as a 5xx, not silently succeed., test_post_postgame_for_missing_game_returns_500()

### Community 19 - "NBA Stats Endpoints"
Cohesion: 0.38
Nodes (7): nba_api CommonAllPlayers, get_data_source Factory, nba_api LeagueGameFinder, NbaApiDataSource (Live Adapter), NBADataSource Protocol, nba_api PlayByPlayV3, StaticSeedDataSource

### Community 20 - "Jobs API Tests"
Cohesion: 0.29
Nodes (3): Tests for /jobs endpoints., Posting ingest/games should return 202 with a job_id., test_post_ingest_games_returns_202()

### Community 22 - "Database Session"
Cohesion: 0.40
Nodes (4): AsyncSession, Async database session factory.  When `test_mode` is True (or the engine is SQLi, get_db(), FastAPI dependency that yields a request-scoped session.

### Community 24 - "Worker Entry Point"
Cohesion: 0.50
Nodes (3): main(), Worker main entry point.  Run with: `rq worker --url redis://... default` The jo, Placeholder for the worker process.      The actual `rq worker` invocation lives

## Knowledge Gaps
- **70 isolated node(s):** `Header`, `AsyncSession`, `BoundLogger`, `Any`, `AsyncClient` (+65 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **19 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_data_source()` connect `Data Source Adapters` to `Detect Runs Worker`?**
  _High betweenness centrality (0.145) - this node is a cross-community bridge._
- **Why does `ingest_game_detail()` connect `Detect Runs Worker` to `LLM Analyst Query`, `Players Endpoints`, `Bad Stretch Detector`, `Data Source Adapters`?**
  _High betweenness centrality (0.115) - this node is a cross-community bridge._
- **Why does `NbaApiDataSource` connect `NBA API Live Adapter` to `Data Source Adapters`?**
  _High betweenness centrality (0.108) - this node is a cross-community bridge._
- **Are the 37 inferred relationships involving `Game` (e.g. with `AnalysisCitation` and `AnalysisQueryRequest`) actually correct?**
  _`Game` has 37 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `GameEvent` (e.g. with `AnalysisCitation` and `AnalysisQueryRequest`) actually correct?**
  _`GameEvent` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `GameEvent` (e.g. with `AsyncSession` and `Depends`) actually correct?**
  _`GameEvent` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `NbaApiDataSource` (e.g. with `NBADataSource` and `StaticSeedDataSource`) actually correct?**
  _`NbaApiDataSource` has 11 INFERRED edges - model-reasoned connections that need verification._