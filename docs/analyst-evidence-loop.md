# Evidence-led analyst implementation

`ANALYST_EVIDENCE_LOOP_ENABLED=true` sends all non-greeting analyst turns through
one bounded orchestrator, replacing the discovery early return and legacy
planner/generator chain. When the flag is false, narrative requests still use this
orchestrator; deterministic table and player routes remain available. Both paths
require a validated active release for narrative answers.
The orchestrator uses the existing configured model, six controlled tools, immutable
backend claims, a separate whole-answer reviewer, and one optional revision/re-review.
The local default is **false**. The production Blueprint enables the loop in
`shadow` mode with a 0.1 comparison sample. It does not enable `llm_primary`.
`ANALYSIS_ANSWER_MODE=deterministic` provides immediate model-free rollback with
the flag enabled. `shadow` delivers backend facts and commits the turn first, then runs
the same metered loop once per committed new turn as a post-response verification in
`app/api/analysis_shadow.py`; its result is diagnostics only and never rewrites the
committed answer.

## Contracts and limitations

`evidence_contracts.py` defines the versioned public/internal contracts. Claim IDs
hash the release, definitions, calculation, subject, scope, value and provenance.
The writer can reference IDs and request rounding; it cannot overwrite claims.
Analytics read the complete applicable release population. Zero-minute player rows
are excluded from appearance denominators; missing rows are coverage gaps.

Discovery starts with observed box scores and the existing catalog, recomputed
from complete release rows under its existing eligibility policies. It introduces
no new automatic window families. Catalog leaders retain the complete qualifier
population. Recent comparisons have distinct recent/prior claims, denominators,
and source windows. Candidate metadata records extreme selection, family, subject,
metric, window, baseline and selection reason. Committed responses alone advance
novelty state. A single-game candidate does not assert a season ranking.

The tools return distinct statuses for ambiguity, empty matches, incomplete
coverage, unsupported scope, dependency failure and success. Search results are
examples, never season denominators. Qdrant failure does not disable SQL claims.
Causal language requires explicit supporting source material and attribution;
hedging, reviewed reports and connected events do not create blanket permission.

## Operations

`resolve_query` returns one explicit `operation` with the scope, and the operation —
not the model's tool choice — decides the calculation. Supported team operations are
record, win/loss/game counts, points totals and averages, points allowed, average
margin, highest/lowest scoring game, best defensive game, largest win/loss margin,
longest losing/winning streak, score-margin swings, numeric-cutoff game counts
(`score_threshold` with a typed subject, comparator and cutoff), period scoring and the
win/loss result split. Player operations are the per-appearance metric, the leaderboard
(`player_leaderboard`) and the canonical derived stats: shooting percentages, double and
triple doubles and games started. Percentages read made and attempted columns together,
so a three-point percentage is never delivered as a total of made threes.

A grouped comparison resolves to a typed `comparison` on the resolved scope, before the
single-valued filters can collapse its populations. Every group carries the rule that
selects its games, so the request never becomes one summed aggregate: home and away;
two named opponents; first and last N games; the two sides of the All-Star break; the
Eastern and Western conferences, read from the stored team conference rather than a
hardcoded list; two named months, when the question compares them; and a recent window
against the whole season. Each
group reports its own games, record, points per game, points allowed and average margin
inside one claim whose eligibility names the group, its kind, the measure and the
coverage, and whose receipts are the games that group actually used. Bench productivity
divides observed non-starter points by every team game in the group, so a game where the
bench scored nothing still counts and a zero-minute row is not an appearance. A player
group divides points by observed appearances only, and the recent-versus-season pair
counts the last N appearances, not the last N team games. The default coverage is the
whole release, so a post-break group includes playoff games; a request that names the
regular season or the playoffs narrows it explicitly. A stated number of games that the
archive contradicts ("the two games against Boston" when four exist) resolves to a
clarification listing the archived games instead of a wrong population.

A comparison splits one population, so only the split axis leaves the scope. Every other
constraint the request states — the opponent, the interval, the phase, the requested
result — is carried as typed shared filters that each group applies before its own rule,
so "compare home and away scoring against Boston in January" compares Boston games in
January instead of every home and away game in the release. The requested statistic and
aggregation travel with the comparison, so a three-point percentage stays made over
attempted and a requested total is not delivered as a per-appearance mean. A window is
applied exactly once, at the basis the comparison declares: a team-game window truncates
the group pool, while a player window truncates appearances after zero-minute rows are
dropped, per player, so a missed team game never consumes one of the N slots.

Windows outside a comparison are a property of the filtered population rather than a
pre-selected list of game IDs: the filters run first and the direction-and-count window
runs once over their result, so a first-N average, a first-N player metric and a
first-N record all read the same first N games. "Between January and March" is one
calendar interval with calendar bounds, a named month honours an explicitly written
year, and an out-of-archive year asks which archived dates to use instead; several
months named without a comparison resolve to a question about interval versus
comparison rather than a silent first-month answer. A follow-up inherits a committed
scope only while the stored release is the active one: a new interval or window replaces
the previous population anchor instead of combining with it, inherited game IDs must
exist in the current release, and a player subject is kept across a release change only
when that player is observed in it.

Windows resolve before any season default: a named month with day endpoints is one
inclusive interval rather than the whole month, "after the All-Star break" starts at the
archive's own mid-February schedule gap, and "How did … do/perform/fare" asks for the
record of the resolved population. A points-average or points-total request emits only
the requested metric, so points allowed is never volunteered.

A follow-up that points back at an earlier game ("in that game", "that stretch", "what
happened next") is answered only from a verified anchor: inherited game IDs, a bounded
date window, or a period set from the server-side session. Without an anchor it clarifies
which game is meant, and the transcript is never treated as evidence.

Three outcomes are decided from the question, never from its wording alone. A supported
ask answers. An ask the archive cannot serve (live, current, future, injury, trade,
standings or betting coverage) resolves to `operation_reason` and refuses with that
reason. An ask whose measurement is undefined (an unsupported ranking, a scoring run, a
close-game cutoff, a quarter superlative) resolves to a typed clarification question and
its options, and never refuses or collapses into season totals because it said "over",
"under", "who led" or "shooting".

Numeric thresholds carry their own metadata: the subject is the Knicks' points, the
opponent's points, the win margin or the loss deficit, the comparator is `>=`, `>`, `<`
or `<=`, and the counted population is reported with the complete denominator. A
leaderboard ranks every player with observed appearances in the complete considered
population, reports every tied leader, and excludes zero-minute rows from appearances.

Each team claim records the operation that produced it and the complete considered
population in `eligibility`, so a selected game is never confused with the population
it was selected from. Counts and rankings consider every game their filters admit:
a descriptive single-game reference resolved earlier in the same question does not
shrink the population, counting wins keeps the losses that form the denominator, and
streak scans run over wins and losses together because a win breaks a losing streak.
Every tied extreme and every tied streak is reported, not only the first.

Swings rank games by the observed range of the Knicks' score margin including a zero
anchor, so a game the Knicks trailed throughout is measured from its largest deficit
to a tie, exactly like the archive's existing swing ranking. Games without play-by-play
margins are not ranked, and the ranking states its own coverage.

## Delivery outcome

The public `refused` flag is derived from the structured outcome, so a delivered answer
can never look like a refusal, and a refusal can never be reported as an answer.

`llm_validated` records whether a reviewed model answer was used, and `degraded`
records whether the turn lost something it expected. They are independent: a
deterministic delivery intended by `ANALYSIS_ANSWER_MODE` is a complete answer with
`llm_validated` false, `degraded` false and no warning, while a primary model, budget
or dependency failure stays `degraded` with a warning. A delivery that produced no
verified facts because a dependency failed is degraded even in a deterministic mode.
`outcome` states the decision in structured form — `answer` when at least one verified
claim is delivered, `clarify` when the turn paused on an ambiguous subject, `refuse`
when the archive explicitly declines the requested ranking — and stays absent when no
decision was reached, so an availability failure is never reported as an abstention.

The reviewer receives a fresh context with the complete proposed answer, backend
claims, selected receipts, capabilities and interpretation policy. Its ordered
assertion spans must reproduce the entire answer exactly. Malformed, incomplete,
unknown and unsupported verdicts fail closed. Typed reference/value checks run
before each review. This safeguard still requires human-labelled calibration;
a reviewer verdict is not proof of truth.

Input packing drops complete records and preserves their server-side references.
UTF-8 byte counts conservatively bound input tokens, including a reserved system
prompt allowance. This underfills context compared with a model-specific tokenizer
and should be measured before promotion. Large claims that do not fit are omitted,
never truncated. Investigation allows two rounds, three tools per round and six
model calls total, including malformed output. Normal lookup uses choose/write/review;
prior-evidence explanation uses write/review. Repairs require capacity and time for
both calls. Replies remain buffered. No prompt logging is introduced.

## Session API

Send previous user/assistant messages as context, plus:

```json
{"question":"Give me an interesting stat", "turn_id":"client-generated-uuid",
 "session_token":null, "expected_revision":0}
```

Replies preserve `answer` and `citations` and add `follow_up_questions` (zero to two),
`session_token`, `revision`, `session_expires_at`, `state_committed`, `session_status`,
`llm_validated`, `degraded` and `outcome`. The opaque token is a bearer secret; do not
log it. Redis owns subject/scope origins, the resolved operation, claims/receipts,
delivered facts, families, release and revision; the raw question is not stored as
conversation authority, and a legacy `intent` entry is dropped at admission. Client
`conversation_state` is ignored by the new
route. Active release identity is pinned and prior references are revalidated
against the newly resolved scope. A changed release clears old evidence.
A session token alone does not admit a new topic. A turn must independently resolve
to archive scope or express a recognized follow-up; unrelated new requests are
refused without calling the provider, even inside an established conversation.

Lua scripts serialize turns using an owner-checked lease, check revisions, and
atomically commit the response and state. Identical turn retries replay the exact
committed reply, including first-turn retries. Different input under the same ID,
stale revisions and concurrent execution return 409 in the shared error envelope
with `error.code` set to `turn_id_reused`, `revision_conflict` or
`turn_in_progress`; `revision_conflict` also carries the authoritative
`error.current_revision`. Sessions and replay records
expire after 24 hours of inactivity, and a request carrying an unknown session
token returns `error.code` `session_expired`. The envelope never reflects the
session token or turn identity. Redis loss gives an explicitly stateless
factual response; a failed commit never claims a committed revision. `session_status`
is `committed`, `retryable` (including deadlines), or `unavailable`; it is null outside
the session protocol. Clients use this field, never warning wording, for recovery.

Both chat surfaces share a transcript that remains fully visible. Each request sends
the ten previous individual messages, excluding the current question. The API keeps
at least a UTF-8-safe opening excerpt of every retained message, then restores
newest detail within a 2,000-byte serialized history allowance. Server session
state separately retains topic, scope, and verified claims. Transcript text has no
evidence authority and is absent from the independent answer reviewer. Model-facing
receipts carry only their evidence ID, source type, game ID and text; provenance stays
in the server registry. On model-enabled turns, a request for a game report or
play-by-play triggers a release- and scope-bound search of the requested collection
before the first model call, even when a previous turn supplied verified claims.
That search consumes a tool slot and the existing investigation deadline. The top
retrieved receipt of that type is placed before claims fill the input budget, and an
answer that cites none of the provided ones is sent back for repair before review.
Archive citations are titled by source type (play-by-play, game report, game record).
The writer returns short answers and may propose up to four follow-up candidates.
The reviewer checks each candidate in its existing call. Only the first two approved
suggestions reach the browser. Rejected suggestions do not discard a valid answer.

The browser's turn state is exactly `idle`, `pending`, or `retryable`; only the latter
two carry a request, and only a retryable turn carries an error. A versioned snapshot
in `sessionStorage` preserves the transcript, session, pending request, and edited draft.
Reload exposes Retry without replacing an edited draft. Abandoned readiness checks
are cancelled and cannot reset a newer conversation. New chat aborts in-flight work
and clears the active conversation. A 409 with
`error.code` `session_expired` starts a visible new-conversation boundary, keeps older
messages readable, retains the submitted question, and replays it tokenless at
revision zero on Retry. `revision_conflict` keeps the same pending turn and adopts
`error.current_revision`; `turn_in_progress` keeps the identical request replayable;
`turn_id_reused` retries the same question under a fresh turn identity without
duplicating it in the transcript. Archive
changes similarly invalidate the old context. Storage failure leaves the in-memory
chat usable and displays a refresh-recovery notice.

The dedicated Analyst view composes shadcn Message Scroller, Message, Bubble, and
Input Group. User turns anchor the viewport; live-edge following yields when the
reader scrolls away, and Jump to latest returns to the current turn. The composer
stays visible, including on narrow screens, and accepts the next draft during a
pending request. Sending the first message preserves composer focus; the field is
outside the resettable scroller context. Restored threads open at their last user
turn. Replies remain
buffered by the existing API: the interface shows real pending activity, not
simulated token streaming. The homepage keeps its existing layout and answer-focus
behavior while sharing the same conversation state.

## Budget operations

The configured production cutoff remains $2. Reservations, cutoff checks and settlement are
atomic. The expected three-call path is reserved before generation; further
investigation/repair reserves remaining capacity before execution. Unknown usage
and uncertain timeouts retain conservative charges. Reported cost settles actual
usage. Shadow uses the same ledger. OpenRouter requests currently allow provider
data collection and fallbacks; deployments that require zero data retention must
restore those routing constraints before enabling the model path.

An absent `ai-budget:YYYY-MM` key blocks all model paths, including legacy callers.
**Do not initialize a lost production ledger to zero.** Reconcile provider billing,
previous reservations and uncertain in-flight requests, then restore the
conservative amount through the existing administrator-controlled Redis access.
The ledger has no automatic expiry. A new month also requires reconciliation.
Local test Redis uses a separate, disposable ledger and never alters production.

Model admission is checked before every provider request: when
`OPENROUTER_ALLOWED_MODELS` is non-empty, a configured chat model outside it fails the
call locally and the turn degrades, so an unadmitted model is never sent off-host.
Mock, keyless and test configurations make no provider request and are not gated.

## Verification and promotion

See the [production runbook](production-runbook.md#verification-and-promotion) for
provider probes, conversation verification, calibration, and promotion gates.
