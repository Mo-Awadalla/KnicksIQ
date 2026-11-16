# Season conversation backend

The public product is one Knicks conversation. This page describes how the API
owns it. The wire contract is in `docs/api.md`.

## Modules

- `app/api/chat.py` owns HTTP: capability header, body validation, rate limits,
  status codes and SSE framing. Its stream response runs each attempt in a task
  it owns and cancels on client disconnect, then waits (shielded) for bounded
  finalization.
- `app/conversation/store.py` is the only writer of conversation state. All
  transitions are Lua scripts over Redis.
- `app/conversation/turn.py` runs provider rounds, lookups, publication, checkpoints,
  finalization, and spending settlement.
- `app/conversation/provider.py` speaks incremental OpenAI-compatible SSE.
- `app/conversation/facts.py` is the lazy, read-only fact desk over the existing
  release-pinned calculations (`AnalystTools`, `analyst_dispatch`) and archive
  retrieval.
- `app/conversation/publication.py` compiles bounded model sentences into safe
  prose or canonical checked statements.
- `app/conversation/gate.py` supplies lexical number and quotation checks.
- `app/conversation/persona.py` holds the voice, the `lookup` tool and message
  bounds.

## State and transitions

Record `chat:session:<sha256(token)>` is a hash: `revision`, `count`, `x:<n>`
exchange JSON, `pending` (`{attempt, index}`), `cmd:<request_id>` command
digests, `commands` and private `facts` scope. `<record>:lease` stores the owner
secret of the pending attempt with a TTL of the turn deadline plus 5 seconds.

| Script | Arguments | Effect |
| --- | --- | --- |
| `BEGIN` | request_id, digest, kind, expected_revision, message, exchange_id, owner, lease_ms | Reconciles an orphan, then: recorded command with another digest gives `request_conflict`; the same command still writing gives `reply_pending`; a recorded command gives `replay` with the current snapshot. Otherwise checks no pending attempt (`conversation_busy`), revision (`revision_conflict` plus revision), capacity (`conversation_full`) and the retry target (`not_retryable`), writes the writing reply, `pending`, the command digest and the lease, and advances revision. Returns `begun`, revision, facts scope and snapshot. |
| `CHECKPOINT` | attempt, owner, base_revision, text | Saves the reply prefix only when the lease holds this owner, `pending` is this attempt and revision equals the base. Returns 1 or 0. Never advances revision. |
| `SETTLE` | attempt, owner, base_revision, status, reason, text, facts | Same ownership checks, then writes the terminal reply, stores facts scope, clears `pending` and the lease, advances revision. Re-running an identical settlement after it applied returns the same result. Otherwise returns `fenced`. |
| `CANCEL` | attempt, expected_revision | Reconciles an orphan; the exact pending attempt at that revision becomes `stopped` with its saved prefix, revision advances and the lease is deleted. Otherwise `not_pending` or `revision_conflict`. |
| `READ` | none | Reconciles an orphan (pending attempt without a lease becomes `interrupted`/`expired`, revision advances) and returns the snapshot. |

Every write renews the 24 hour retention; a read without reconciliation does
not. Only these scripts change revision, so a stopped, expired or superseded
owner cannot publish: its next checkpoint or settlement is fenced.

## One attempt

1. `BEGIN` resolves replay before any provider configuration, database, tool or
   budget work.
2. Missing provider configuration or a model outside
   `OPENROUTER_ALLOWED_MODELS` settles `interrupted`/`unavailable`. There is no
   mock fallback; `report_llm` keeps its separate offline report adapter.
3. If the current message explicitly asks for an exact metric, score, record or
   game detail, the desk looks it up first and the writer sees those facts.
   Opinions and greetings are not prefetched. The writer is instructed to lead
   with basketball reasoning, but may request a bounded lookup. Earlier claims
   are never reused; only resolved scope persists for referential follow-ups.
4. Each provider call reserves `ANALYST_CALL_RESERVATION_USD` against the
   monthly cutoff first and settles in `finally`. Only a reported `usage.cost`
   lowers the charge; unknown, cancelled, malformed and usage-less calls keep
   the full reservation. The Redis ledger is an application cutoff, not a
   billing ceiling.
5. Text passes through `Publication` before `CHECKPOINT` and public `delta`
   emission. `[[f1]]` expands to the complete checked statement. A scalar player
   stat sentence can wait for up to 48 trailing reference characters. Its value,
   player, metric, and opponent must agree with server-only support. A successful
   binding emits the canonical statement, never the model's numeric wording.
   Repeated source authorities appear once per turn. Unsupported framing,
   unbound quantities, unknown references, and unsupported quotations are withheld.
   Scores, dates, percentages, and narrative facts keep the whole-statement
   reference path. List markers, the season label, basketball concepts, and
   explicit word-number hypotheticals remain conversational. Quoted terms need
   a naming or criterion frame. Actual attribution requires a checked reference.
   One continuation receives the released prefix, private reason and detail, and
   at most 448 characters of rejected draft. That draft is not logged, persisted,
   or shown to the user. A second violation ends the reply
   `interrupted`/`incomplete`.
   Settlement preserves every emitted character, including trailing whitespace.
6. Prose and tool calls may share a provider round. Every tool call ID gets one
   result. Lookups run sequentially on the attempt's one database session;
   unknown tools, invalid arguments and excess calls get explicit errors.
7. Bounds: 6 provider calls, 2 tool rounds, 3 lookups per round, 600 output
   tokens per call, 4,000 reply characters, `ANALYST_INPUT_TOKENS` bytes of
   persona, history and message, `ANALYST_EVIDENCE_TOKENS` bytes of facts, and a
   generation deadline 3 seconds inside `ANALYST_DEADLINE_SECONDS`.
8. Finalization has 5 seconds inside the lease to close the database session and
   `SETTLE`. A lost acknowledgement yields `recovery`/`outcome_unknown`; the next
   read establishes the outcome.

Private quality data (calls, tool rounds, lookups, gate violations,
continuations, truncation, reply length) is logged per attempt as
`conversation.turn` without any message or reply text.

## Limits of the gate

The gate checks numbers, references and quotations. It cannot establish the
truth of arbitrary prose. Invented events, causal stories, relevance, topic
redirection, refusals and voice remain real-provider quality risks that need
bounded real-provider acceptance; scripted upstream fixtures prove only the
protocol.

## Fact atoms

The desk projects each complete verified claim with its actual game population,
phase, opponent and date/window context. Single-game points identify that game,
not a season-wide sample. The shared player producer is phase-neutral; the
verified claim supplies phase. Compact multi-game context does not list every
game or opponent.

Reference identity includes private source authority as well as displayed text.
Equal numbers or summaries from different populations therefore remain distinct
facts. Claim and evidence IDs never appear in public replies.

`PublishedClaim` retains scalar support, source game identities, and team
identities only in the current turn. Alias sets come from the loaded release
roster and canonical team metadata. Shared aliases remain ambiguous. Model
lookups still receive only `ref` and `text`.

For an event-window lookup, `FactDesk` publishes only the bounded, chronological
per-event receipts. It does not expose the aggregate claim or composite window
receipt. Each public event fact contains one clock and its source description.
An event carries its own recorded score only when the source row has one.
Missing scores stay missing; adjacent rows never fill them in.

Event intervals stay on the requested periods. An opening window in the second
half means Q3, a closing window means Q4, and a regulation window excludes
overtime. Additional periods render as `OT`, `2OT`, and so on. A missing
quantity in “last minute” means 60 seconds. When more than three events match,
chat receives the first three plays for an opening window or the final three
for a closing window, plus a coverage note. The full
event-window claim stays out of public facts.
