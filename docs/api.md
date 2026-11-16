# API reference

KnicksIQ's public API is one season conversation plus health probes. Development
exposes Swagger at `/docs`; production disables Swagger, ReDoc and the OpenAPI
document. Production rejects plain HTTP behind its TLS edge, keeps the 128 KiB
body cap, per-client rate limits and the security headers, and allows the
`X-Chat-Token` header through CORS.

## Production endpoints

- `GET /health/live`: process liveness.
- `GET /health/ready`: Postgres and active-release readiness plus optional
  dependency status. Returns 503 without a validated active release. The
  release smoke reads `data_version` here; no paid question is sent.
- `POST /chat/turns`, `GET /chat/current`, `POST /chat/cancel`: the conversation.

Nothing else is routed in production. The former archive, game, player, team,
report and analysis endpoints are retired from every public profile. Games,
reports, calculations, ingestion and MCP tools remain internal.

## Conversation

Every chat request carries an opaque capability in `X-Chat-Token`
(`[A-Za-z0-9_-]{32,128}`, created randomly by the browser tab). It never appears
in a URL. The server keys state by its SHA-256 and treats it as access only, not
as topical or factual authority.

### Snapshot

```ts
type Reply =
  | { status: 'writing'; id: string; text: string }
  | { status: 'complete'; id: string; text: string }
  | { status: 'stopped'; id: string; text: string }
  | { status: 'interrupted'; id: string; text: string; reason: Reason }
type Reason = 'disconnected' | 'expired' | 'unavailable' | 'budget' | 'deadline' | 'incomplete'
type Exchange = { id: string; message: string; reply: Reply }
type Snapshot = { revision: number; exchanges: Exchange[] }
```

An exchange ID is the request ID of the message that created it. A reply ID is
the request ID of the attempt that wrote it. Snapshots contain no facts,
references, tools, provider data or spending details.

### `POST /chat/turns`

```json
{"kind": "message", "request_id": "<uuid>", "expected_revision": 0, "message": "Were we contenders?"}
{"kind": "retry", "request_id": "<new uuid>", "expected_revision": 4, "exchange_id": "<uuid>"}
```

`request_id` and `exchange_id` are canonical lowercase UUIDs. A message is 1 to
1,200 characters. Retry replaces the reply of the latest exchange when it is
`stopped` or `interrupted`; it never duplicates the user message.

An accepted command returns `text/event-stream` (`Cache-Control: no-store`,
`X-Accel-Buffering: no`). Each frame is `event: <name>` plus one JSON `data`
line:

| Event | Data | Meaning |
| --- | --- | --- |
| `accepted` | `request_id`, `exchange_id`, `revision` | The attempt began at this revision. |
| `checking` | `request_id` | A quiet cue that exact facts are being checked. |
| `delta` | `request_id`, `text` | Released text, already saved in the snapshot. |
| `settled` | `request_id`, `snapshot` | The canonical snapshot after settlement. |
| `recovery` | `request_id`, `code`, `retryable` | The outcome is not established by this stream. |

Recovery codes are `outcome_unknown` (the terminal write was not confirmed) and
`fenced` (the attempt lost ownership because it was stopped, expired or
superseded). Both carry `retryable: false`; read `GET /chat/current` instead of
resending. Re-posting an already recorded command returns a single `settled`
frame with the current snapshot and no deltas, without provider, database or
spending work.

A missing provider credential, a non-allowlisted model, the monthly cutoff,
provider failure or the turn deadline settle the reply as `interrupted` with a
reason. They never produce a mock answer.

### `GET /chat/current`

Returns the bare snapshot, including a live `writing` reply and its saved
prefix. An unknown capability returns `{"revision": 0, "exchanges": []}`. A
`writing` reply whose owner lease has expired is settled `interrupted`
(`expired`) atomically during the read. The read never regenerates anything.

### `POST /chat/cancel`

```json
{"request_id": "<attempt uuid>", "expected_revision": 3}
```

Stops exactly that writing attempt and returns the snapshot with the reply
`stopped` and its saved prefix. A completed, already stopped or superseded
attempt returns `409 not_pending`.

### Errors before acceptance

| Status | Code |
| --- | --- |
| 400 | `invalid_token` |
| 409 | `revision_conflict` (with `current_revision`), `request_conflict`, `reply_pending`, `conversation_busy`, `conversation_full`, `not_retryable`, `not_pending` |
| 413 | `request_too_large` |
| 422 | `invalid_request` |
| 429 | `rate_limited` |
| 503 | `unavailable` |

### Retention and capacity

A conversation keeps at most 40 exchanges and 120 recorded commands; after that
the next send returns `conversation_full` and the browser starts a new chat.
The record expires 24 hours after its last write. Sends, checkpoints, settlements,
Stop and orphan reconciliation renew it; plain reads do not. There is no
listing or delete endpoint. New chat abandons the capability.

## Development-only routes

The development router adds `GET /health`, `GET /health/rag` and the admin job
routes. Postgame reports are generated offline with
`python -m app.services.report_generator GAME_ID`. Production data is loaded
only through the validated release CLI.

## Errors and tracing

Errors use a stable envelope:

```json
{"error": {"code": "invalid_token", "message": "..."}, "request_id": "..."}
```

Every response returns `X-Request-ID`, accepts an optional caller-provided
`X-Request-ID`, and includes security and timing headers. Telemetry drops
request bodies and headers, message, text, content, tool and token fields, and
provider error bodies.
