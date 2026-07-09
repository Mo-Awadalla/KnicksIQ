# MCP Tools Reference

The KnicksIQ MCP server exposes basketball-specific tools to LLM
clients via the official [Model Context Protocol](https://modelcontextprotocol.io/)
Python SDK. Tools are read-only and do not mutate game data.

## Transports

- **stdio** — for local clients like Claude Desktop. Run with:
  ```
  uv run --package knicksiq-mcp python -m mcp_app.server --transport stdio
  ```
- **SSE** — for HTTP-based clients. Run with:
  ```
  uv run --package knicksiq-mcp python -m mcp_app.server --transport sse
  # Listens on :8001 by default (configurable via SSE_PORT)
  ```

## Tools

### `knicks.get_games`

List games. Optional filters.

**Parameters:**

| Name    | Type   | Description                            |
| ------- | ------ | -------------------------------------- |
| season  | string | e.g. `2024-25`                        |
| team_id | string | Filter to games involving this team    |
| limit   | int    | Default 20                             |

**Returns:** `list[GameSummary]`

### `knicks.get_game`

Single game detail.

**Parameters:**

| Name    | Type | Description |
| ------- | ---- | ----------- |
| game_id | int  | Internal id |

**Returns:** `GameSummary | null` (null if not found)

### `knicks.get_box_score`

Returns game-level totals (home/away score, status, margin).
Player-level box scores will arrive in a later phase.

**Parameters:**

| Name    | Type | Description |
| ------- | ---- | ----------- |
| game_id | int  | Internal id |

**Returns:** `dict` (or `{"error": "game_not_found"}`)

### `knicks.get_play_by_play`

Get the play-by-play events for a game, normalized to the
canonical event schema.

**Parameters:**

| Name    | Type | Description |
| ------- | ---- | ----------- |
| game_id | int  | Internal id |
| period  | int | Optional, 1-4 |

**Returns:** `list[GameEvent]`

### `knicks.find_scoring_runs`

Find scoring runs in a game. Uses the precomputed
`scoring_runs` table if populated; otherwise runs the
detector live on the play-by-play.

**Parameters:**

| Name    | Type   | Description                       |
| ------- | ------ | --------------------------------- |
| game_id | int    | Internal id                       |
| team_id | string | Optional: filter to this team     |

**Returns:** `list[ScoringRun]`

### `knicks.find_bad_stretches`

Find bad stretches (opponent runs + droughts + turnover clusters)
for a game. Cached or live, same as `find_scoring_runs`.

**Parameters:**

| Name    | Type | Description |
| ------- | ---- | ----------- |
| game_id | int  | Internal id |

**Returns:** `list[BadStretch]`

## Logging

Every tool call is logged with:

- `id` — short call id
- `tool` — tool name
- `params` — input parameters
- `duration_ms` — wall-clock duration
- `status` — `ok` / `error`
- `error` — error message (if any)

The default logger writes to stdout. In a production deploy,
route the logs through your aggregator (Loki, ELK, etc.).

## Connecting from Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "knicksiq": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/KnicksIQ",
        "run", "--package", "knicksiq-mcp",
        "python", "-m", "mcp_app.server",
        "--transport", "stdio"
      ]
    }
  }
}
```

## Safety

- All tools are read-only by default.
- Tools never execute shell commands or write to the filesystem.
- The MCP server does not accept user-controlled job enqueue or
  data mutation requests. (The API does, via authenticated admin
  endpoints — a Phase 8+ follow-up.)
- Tool calls are rate-limited by the underlying transport; the
  MCP server does not impose additional limits today.
