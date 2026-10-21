# API reference

KnicksIQ is a JSON FastAPI service. Development exposes Swagger at `/docs`;
production disables Swagger, ReDoc, and the OpenAPI document.

All public basketball responses are scoped to the validated active release.
`game_id` and `player_id` path values are internal integer IDs. List endpoints
use `limit` and `offset` where supported.

## Production endpoints

### Operational

- `GET /health/live`: process liveness.
- `GET /health/ready`: Postgres and active-release readiness plus optional
  dependency status. Returns 503 without a validated active release.
- `GET /`: service metadata.
- `GET /archive/status`: active season, data version, game/report counts, and
  supported capabilities.

`GET /health` and `GET /health/rag` are development diagnostics and are not in
the production router.

### Archive reads

- `GET /teams`, `GET /teams/{team_id}`
- `GET /players`, `GET /players/{player_id}`
- `GET /games`, `GET /games/{game_id}`
- `GET /games/{game_id}/box-score`
- `GET /games/{game_id}/play-by-play`
- `GET /games/{game_id}/runs`
- `GET /reports`, `GET /reports/{report_id}`

Only reviewed reports from the active release are public. The legacy
`GET /games/{game_id}/bad-stretches` route remains development-only.

### Analyst query

`POST /analysis/query` accepts:

```json
{
  "question": "What was the Knicks' record against Boston?",
  "season": "2025-26",
  "turn_id": "client-generated-uuid",
  "expected_revision": 0,
  "context": []
}
```

The response contains a grounded answer, claim-level citations, warnings,
`refused`, `degraded`, `llm_validated`, active data version and request ID.
`llm_validated=true` marks an answer that passed the independent reviewer.
`degraded=true` marks deterministic cited facts delivered after a provider,
budget, timeout or validation failure.

Season-level records and stats default to the regular season. The answer states
the phase, for example `53-29 in the regular season`. The all-phase record,
`69-32`, appears only when the question says overall, including playoffs or all
phases. Opponent matchups span all phases and carry phase breakdowns.

`refused=true` means the answer declined or explained coverage. A validated
refusal returns `llm_validated=true`, `refused=true`, `degraded=false` and may
have zero citations. A pre-model refusal returns `refused=true`,
`llm_validated=false`, `degraded=false`, no citations and the refusal warning.
`ask_clarification` is not a refusal. A refusal is a normal HTTP 200 response.

The evidence loop exposes nine tools to the model: `get_player_stats`,
`get_team_stats`, `compare_windows`, `discover_facts`, `search_archive`,
`get_evidence`, `get_game_flow`, `get_team_splits` and `get_period_scoring`.
Quarter, period, play-by-play and split questions are supported. Internal
retrieval plans, claim-validation comparisons, classifier data, evidence, routes
and tool traces are excluded in production.

Explicit instruction override, wagering and out-of-archive date requests are
refused before any provider call. Live, injury, trade, prediction and current
questions reach the analyst, which declines or explains coverage without
inventing data. Rate-limit failures return 429.

The public schema is identical in `deterministic`, `shadow` and `llm_primary`.
In shadow mode the user receives the deterministic response. In primary mode,
failure of Qdrant, OpenRouter, Redis-backed AI budgeting or claim validation
returns that same deterministic response with `degraded=true`.

## Development-only mutation routes

The development router also includes job enqueue/status, run detection,
postgame report generation, and report deletion. These routes exist for offline
workflows and tests and are intentionally absent in production. Production data
is loaded only through the validated release CLI.

## Errors and tracing

Errors use a stable envelope:

```json
{
  "error": {"code": "http_404", "message": "..."},
  "request_id": "..."
}
```

Validation errors use `invalid_request`; unexpected errors use
`internal_error`. Every response returns `X-Request-ID`, accepts an optional
caller-provided `X-Request-ID`, and includes security and timing headers.
