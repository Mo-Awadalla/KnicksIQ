# API Reference

The KnicksIQ API is a FastAPI service. All endpoints are JSON.
The full OpenAPI schema is available at `/docs` when the service is running.

## Conventions

- All list endpoints accept `limit` (default 50, max 200) and `offset`
  (default 0) for pagination.
- All timestamps are ISO 8601 with timezone.
- All internal `id` columns are integers; `team_id` columns are
  abbreviations like `NYK`.
- `game_id` in the URL path is the **internal** integer id, not the
  NBA's `nba_game_id` string.

## Endpoints

### Health

#### `GET /health`

Liveness probe. Returns `{"status": "ok"}`.

#### `GET /`

API metadata. Returns the service name, description, and a link to docs.

### Teams

#### `GET /teams`

List all teams (30 NBA teams in the seed data).

#### `GET /teams/{team_id}`

Get one team by abbreviation. `404` if not found.

### Players

#### `GET /players`

Query players.

Query params:

- `team_id` — filter by team abbreviation (e.g. `NYK`)
- `search` — case-insensitive name search
- `limit`, `offset` — pagination

#### `GET /players/{player_id}`

Get one player by internal id. `404` if not found.

### Games

#### `GET /games`

List games.

Query params:

- `season` — e.g. `2024-25`
- `team_id` — filter to games involving this team
- `status` — `scheduled` / `live` / `final` / `postponed`
- `limit`, `offset` — pagination

Returns a list of `GameSummary` objects (no team detail to keep
the response small).

#### `GET /games/{game_id}`

Game detail. Returns `GameDetail` with home/away team objects
embedded.

#### `GET /games/{game_id}/play-by-play`

Get the play-by-play events for a game, ordered by `(period, sequence)`.

Query params:

- `period` — optional, 1-4

#### `GET /games/{game_id}/runs`

Get precomputed scoring runs (run detection is a separate
background job — see `/games/{id}/detect-runs`).

Query params:

- `team_id` — filter to runs by this team

Returns an empty list if the detection job hasn't been run yet.

#### `GET /games/{game_id}/bad-stretches`

Get precomputed bad stretches. Same caching behavior as `/runs`.

#### `POST /games/{game_id}/detect-runs`

Enqueue a job to (re)run scoring-run and bad-stretch detection
on the game's events. Returns `202 Accepted` with a `job_id`.

### Jobs

#### `POST /jobs/ingest/games`

Body: `{ "season": "2024-25" | null }`

Enqueue an ingestion job. `202 Accepted` with a `job_id`.

#### `POST /jobs/ingest/game/{game_id}`

Enqueue ingestion for a single game's play-by-play.

#### `GET /jobs/{job_id}`

Get job status. Response includes `status`, `payload`, `result`,
`error_message`, and timing fields.

### Reports

#### `POST /reports/postgame`

Generate a postgame autopsy report.

Body:

```json
{
  "game_id": 1,
  "include_tool_trace": true,
  "include_sources": true
}
```

`201 Created` with the report, including:

- `title`, `summary`, `turning_point`, `best_stretch`, `worst_stretch`
- `player_notes` (list of strings)
- `suggested_adjustments` (list of strings)
- `sources` (list of source records)
- `tool_calls` (list of tool-call records with latency in ms)

`404` if the game is not found.

#### `GET /reports`

List saved reports (newest first).

Query params:

- `game_id` — filter to one game's reports
- `limit`

#### `GET /reports/{report_id}`

Get one report with full tool trace. `404` if not found.

#### `DELETE /reports/{report_id}`

Delete a report. `204 No Content` on success.

## Error responses

| Status | When                                       | Body                          |
| ------ | ------------------------------------------ | ----------------------------- |
| 404    | Resource not found                         | `{"detail": "..."}`           |
| 422    | Validation error (Pydantic)                | `{"detail": [{...}]}`         |
| 500    | Unhandled server error                     | `{"detail": "Internal..."}`   |

## Example: end-to-end report generation

```bash
# 1. Pick a game
curl -s 'http://localhost:8000/games?team_id=NYK' | jq

# 2. Trigger run detection
curl -s -X POST 'http://localhost:8000/games/1/detect-runs' | jq
# => { "job_id": "...", "status": "queued" }

# 3. (Wait for worker; in a real env, poll /jobs/{id})
curl -s 'http://localhost:8000/jobs/{job_id}' | jq

# 4. Read the runs
curl -s 'http://localhost:8000/games/1/runs' | jq

# 5. Generate the report
curl -s -X POST 'http://localhost:8000/reports/postgame' \
     -H 'Content-Type: application/json' \
     -d '{"game_id": 1, "include_tool_trace": true, "include_sources": true}' | jq
```
