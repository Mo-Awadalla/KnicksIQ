# Evidence-led analyst implementation

The opt-in `ANALYST_EVIDENCE_LOOP_ENABLED=true` route replaces the discovery early
return and legacy planner/generator chain with one bounded orchestrator. It uses
the existing configured model, controlled tools, immutable backend claims,
a separate whole-answer reviewer, and one optional revision/re-review. The default
local default remains **false**. The production Blueprint enables the loop and
`llm_primary` following the owner’s explicit production activation request.
`ANALYSIS_ANSWER_MODE=deterministic` provides immediate model-free rollback with
the flag enabled. `shadow` exercises the same metered loop and delivers facts.

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

Canonical discovery verifies its complete SQL-bound source corpus before lexical
retrieval. Integrity preparation uses the configured investigation budget (20 seconds
in staging), inside the unchanged 30-second HTTP request deadline. The four-second
local retrieval deadline then covers lexical search, ranking and receipt admission,
not source transfer and integrity verification. No source check is cached or skipped;
invalid proof and slow lexical retrieval still return dependency failure.

The tools return distinct statuses for ambiguity, empty matches, incomplete
coverage, unsupported scope, dependency failure and success. Search results are
examples, never season denominators. Qdrant failure does not disable SQL claims.
Causal language requires explicit supporting source material and attribution;
hedging, reviewed reports and connected events do not create blanket permission.

The reviewer receives a fresh context with the complete proposed answer, backend
claims, selected receipts, capabilities and interpretation policy. Its ordered
assertion spans must reproduce the entire answer exactly. Claim provenance links
in `supporting_evidence_ids` are not permission to cite an omitted receipt: review
evidence references must come from the admitted `evidence` array. A complete
immutable claim can support a span through `supporting_claim_ids` alone when its
receipt is omitted. Malformed, incomplete, unknown and unsupported verdicts fail
closed. Typed reference/value checks run before each review; strict reference
validation is unchanged. This safeguard still requires human-labelled calibration;
a reviewer verdict is not proof of truth.

Input packing admits or drops whole records and preserves their server-side
references. At each mandatory-context, claim-group and evidence boundary, UTF-8
bytes account for the actual system instructions, serialized user payload and,
in `json_schema` mode, the actual scoped provider schema. The existing 8000-byte
input cap and evidence allowance are unchanged. Strict mode retains only the
protocol title in the user's `schema` field; validation constraints appear once,
in the provider schema. Nonsemantic schema titles, descriptions and defaults are
compacted without changing allowed values, reference enums, exact review spans,
or the two-follow-up limit. JSON-object mode still carries its user schema and
requires local validation. This conservative bound underfills context compared
with a model-specific tokenizer. Large records are never truncated; requested
record pairs and selected narrative/scalar game sets are indivisible and fall
back completely if they cannot fit. Investigation allows two rounds, three tools
per round and six model calls total, including malformed output. Normal lookup
uses choose/write/review; prior-evidence explanation uses write/review. Repairs
require capacity and time for both calls. Replies remain buffered. No prompt
logging is introduced.

Model-input claim records omit inapplicable nullable fields; the immutable server
registry and public claim JSON remain unchanged. Typed values, requested scope,
population and provenance remain intact. Selected scalar game sets must fit
completely before a writer call; otherwise the backend keeps the complete
factual fallback rather than paying for a known-incomplete proposal.

## Deterministic requested statistics

The evidence-loop route calculates requested leaders, home/away and win/loss
comparisons, monthly records, first/last team-game records, team quarter scoring,
player recent-versus-season averages, and single-game player profiles from the
active release. Comparison groups reuse `team_scope.comparison_groups`.
Bench scoring divides nonstarter points by team games; shooting percentages
divide total makes by total attempts. Player averages use observed appearances,
not team games. Leader ties and tied selected games remain complete.
The orchestrator advertises `get_team_stats` for team-wide player scoring/statistic
leaders over the complete requested team-game population, including ties.
`discover_facts` supplies candidate facts, not an authoritative substitute for a
requested multi-game leader calculation. The existing backend calculation and
complete-population validator remain responsible for this distinction.


Fallback eligibility requires the exact requested subgroup, period, player
appearance window, or selected-game population and metric. Every requested
comparison operand, quarter, or profile statistic must be available; an arbitrary
subset is not sufficient. A player's selected-game profile includes points,
rebounds, assists, and the final score. Backend fallback renders all verified
claims without the former three-claim truncation; model proposals retain their
30-claim limit.

Comparison reuse also requires the exact requested value keys, not merely the
generic `team_comparison` metric and matching groups. A record request preserves
both wins and losses; points-allowed comparisons average opponent scores, not
Knicks scoring. A recent-versus-season comparison clears only the baseline's
explicit game/date/relative window and retains its other requested filters.
Both operands use the corresponding positive-minute player appearances.

The advertised player and team metric vocabularies also define `ToolCall.metric`.
Team-only selectors are rejected for player calculations and window comparisons
before dispatch; raw player-column calculations retain their existing metric set.
Once both scope-matched record counts exist, the loop drafts a `ProposedAnswer`
directly instead of resending the larger tool-orchestration schema. Both canonical
claim IDs are mandatory, are packed atomically, and retain their complete
population and provenance. A missing count or an over-budget pair triggers the
complete factual fallback. The existing repair, whole-answer review, call
accounting, deadlines and original input/output limits still apply.
Prepared canonical narrative and scalar-game populations also draft directly:
their backend investigation has already completed, so another tool-action schema
adds no information. Every selected game and requested metric remains mandatory.

Quarter calculations currently support team points per game only. Quarter totals,
other quarter box-score statistics, and player quarter statistics remain
unsupported rather than being answered with a different metric. Statistical game
extrema return final scores and requested margins using the existing canonical
selector; narrative requests retain their complete descriptive stories.
For example, explaining the best defensive game returns its final score and names
the existing minimum-opponent-points selection measure; it does not introduce
unrequested quarter statistics or claim a causal explanation.
Primary scalar extrema validation requires every selected or tied game's final
score and each requested margin; it does not require a narrative-only claim.
The independent whole-answer reviewer remains mandatory.

Delivered scalar statistics identify opponent, phase, date window and any
home/away or result filter. Threshold game counts also name the scoring team,
comparison operator and cutoff; `eligibility.score_predicate` preserves that
definition alongside the full contributing game population.
Yearless calendar dates resolve only within the release-supported calendar;
ambiguous or invalid dates ask for clarification. An uncommitted conversational
reference requires both a game/date and the referenced event, stretch, or claim,
plus comparison inputs when needed. Scoped ambiguous game questions offer the
actual archived dates without asserting a matching-game count. Ambiguous scoring
sequences ask for both the game and the run measure/time-window definition.
A request for two games does not silently expand to all matching games.


## Session API

Send previous user/assistant messages as context, plus:

```json
{"question":"Give me an interesting stat", "turn_id":"client-generated-uuid",
 "session_token":null, "expected_revision":0}
```

Replies preserve `answer` and `citations` and add `follow_up_questions` (zero to two),
`session_token`, `revision`, `session_expires_at`, `state_committed`, and
`llm_validated`. The opaque token is a bearer secret; do not
log it. Redis owns subject/scope origins, intent, claims/receipts, delivered facts,
families, release and revision. Client `conversation_state` is ignored by the new
route. Active release identity is pinned and prior references are revalidated
against the newly resolved scope. A changed release clears old evidence.

Lua scripts serialize turns using an owner-checked lease, check revisions, and
atomically commit the response and state. Identical turn retries replay the exact
committed reply, including first-turn retries. Different input under the same ID,
stale revisions and concurrent execution return 409. Sessions and replay records
expire after 24 hours of inactivity. Redis loss gives an explicitly stateless
factual response; a failed commit never claims a committed revision. The browser
retains turn IDs for retry and prevents synchronous duplicate submission.

Both chat surfaces share a transcript that remains fully visible. Each request sends
the ten previous individual messages, excluding the current question. The API keeps
at least a UTF-8-safe opening excerpt of every retained message, then restores
newest detail within a 2,000-byte serialized history allowance. Server session
state separately retains topic, scope, and verified claims. Transcript text has no
evidence authority and is absent from the independent answer reviewer. The writer
returns short answers by default and can offer two follow-up questions in the same
call. The reviewer checks suggestions in its existing call; rejected suggestions
are omitted while a valid answer survives.

The browser stores a versioned transcript, session identity, expiry, archive version,
and exact pending turn in `sessionStorage`. Reload exposes Retry for an interrupted
turn. New chat aborts in-flight work and clears the active conversation. A 409 with
`session_expired` starts a visible new-conversation boundary, keeps older messages
readable, and leaves the submitted question ready for Retry or editing. Archive
changes similarly invalidate the old context. Storage failure leaves the in-memory
chat usable and displays a refresh-recovery notice.

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

## Verification and promotion

Before any paid capability or evaluation run, the no-spend regression path is the
existing isolated SQL and real local Redis HTTP setup with empty live provider
credentials. Run `test_analyst_payload_http.py`, `test_analyst_value_format_http.py`
and `test_loop_review_http.py`. The behavioral
`test_strict_format_bounded_complete_population_http` cases cover a positive-minute
appearance average, both requested record counts, and tied team-wide leaders over
all three requested games. Fixed expected SQL values, complete citation populations,
whole-answer review and committed replay are checked; their scripted provider
boundary includes the external scoped schema in every dispatched input byte count.
These tests are synthetic protocol evidence, not live-model quality evidence.

For the private captured-wire dry diagnostic, rebuild payload selection with the
new packer and a recording, no-network adapter; count the actual system/user/scoped
schema bytes at dispatch, confirm every input is at most 8000 UTF-8 bytes, and
compare retained claims with their immutable registry objects. Check complete
requested record/narrative groups, admitted evidence/fact/review reference enums,
exact review spans and the unchanged follow-up bound. Capture any over-budget
mandatory group as a complete factual fallback, never a partial authoritative
answer. This offline replay spends nothing and cannot certify new model answers
or replace fresh prerequisite admission and the original quality evaluations.

Run `uv run --package knicksiq-api python -m app.evaluation.analyst_probe` against the
configured provider. `ANALYST_PROVIDER_FORMAT=json_schema` enables strict schema
and OpenRouter `require_parameters`; the explicit default `json_object` still
requires local schema validation. No model substitution occurs.

Run the repeated conversation harness against a private API:

```sh
uv run --package knicksiq-api python -m app.evaluation.analyst_evaluation \
  --base-url http://127.0.0.1:8000 --repetitions 5 \
  --output docs/release-evidence/analyst-evidence-v1/conversations.json
```

The harness stops if provider capability fails. Automated protocol tests use
scripted models and actual local Redis; they do not measure provider answer
quality or count toward LLM release success. Human review, held-out reviewer
calibration, search Recall@5 on labelled top-five-satisfiable tasks, answerable
completion, naturalness and latency classifications must be supplied separately.
Missing measurements fail the gate helper. Existing release approvals remain
required; this implementation does not automatically promote or deploy.

The private original120 runner is `app.evaluation.guarded_release`: `admit` verifies
current key credit, model/provider parameters and prices, exact archive/index
identities, and the normal monthly ledger without sending a completion. `collect`
runs either the full primary cohort or its distinct fixed-ID 10% shadow cohort.
Both use the same exclusive goal journal, original request ceilings and aggregate
$2 authority, including retained historical charges. Uncertain transmission,
missing cost, unexpected provider, exceeded bounds or invalid analyst protocol
stop later calls; admission and synthetic HTTP safety checks are not
live-provider quality certification.

The counted adapter validates `Action`, `ProposedAnswer` and `AnswerReview`
inside its failure boundary, before returning content to the analyst loop.
Known provider cost is settled before schema validation; malformed content does
not erase that cost or make a known transmission financially uncertain. A
protocol failure stops the shared journal. When every ticket in a new normal
reservation has a trusted settled receipt, its known cost and unused slots
settle normally; genuinely uncertain exposure remains held. The runner cannot
silently fall back and continue paying for later cohort cases.

Stopped journals, goal bindings and their exclusive anchors remain immutable.
The original single-successor owner grant remains limited to its one attempt.
A separate exact known-cost-continuation grant permits fresh descendants only
after a verified source fix: the predecessor must have a ticket-joined private
protocol failure, and every fresh transmission and normal reservation must have
trusted, non-uncertain settlement. New financial uncertainty blocks continuation.
Both `--successor-authorization` and `--predecessor-goal` remain required.

Every descendant inherits all ancestral requests, costs, original uncertainty
and exact retained holds. The initial continuation includes all 27 prior primary
requests against the unchanged 720 ceiling. Each predecessor can admit only one
child, using an exclusive grant-and-predecessor-journal anchor. The monthly
authority cannot decrease; its minimum adds only the immediate predecessor's
fresh settled costs, not ancestral charges or held amounts again. The $2 cutoff
and original stage limits remain unchanged. Old holds cannot be reused, released
or replaced by fresh reservations.

Internal session and private quota identities use the admitted goal binding,
not the shared grant, so later descendants cannot replay earlier attempts.
External frozen turn/request IDs and shadow membership stay unchanged.
Ordinary session behavior is restored when the controller exits. Exact provider
response bytes are durably retained with mode `0600` before status, JSON or schema
parsing. Private diagnostics retain the ticket, raw SHA, typed validation
locations/types and finish reason. Neither those bytes nor a new source hash
authorize resuming a stopped journal or bypassing a quality gate.

The resource network is internal and cannot reach OpenRouter. For paid verification,
attach only the disposable verifier to both exact admitted resource and outbound
networks, using the inspected PostgreSQL address. The guard checks both network
IDs, the PostgreSQL system ID and connection address, and every Redis/Qdrant target.
Existing service containers and their network membership remain unchanged.
The PostgreSQL-shared namespace remains valid for isolated, no-egress checks.
Docker inherits PostgreSQL's hostname in that mode, so hostname is not verifier
identity. Create/start the controller-owned verifier first, then pass its full
daemon ID with `docker exec -e KNICKSIQ_VERIFIER_CONTAINER_ID=<64-hex-id>`.
Missing identity, a substituted PostgreSQL identity or a wrong resource network
is denied. Use `QDRANT_URL` for the actual Qdrant endpoint setting.

After both original quality cohorts pass, `app.evaluation.guarded_load` runs the
unchanged `tools/release/stress.py` workload: warmup, 61-second cooldown, ten
archive readers and ten distinct analyst requests over 30 seconds. Its counted
load stage uses the same admitted journal and normal monthly reservations.
The fixed load ceiling covers eleven turns at six calls each; it does not change
the original primary/shadow ceilings, quotas or latency thresholds.
Responses stay buffered until counted accounting and factual validation finish;
an execution failure cannot expose a successful response before stopping the stage.

Admission requires `--primary-score`, `--shadow-score` and `--shadow-record`,
in addition to the disabled score and observations. Scores must be produced by
the existing original-workload scorer and bound to the same goal's full
primary/shadow observations. The existing staged shadow record must bind the
actual captured turns, fixed membership, source/bundle/configuration and original
shadow validator. Transport-complete fallback stages and synthetic safety
receipts do not satisfy these quality prerequisites.

The production model is `deepseek/deepseek-v4.1-flash`, selected explicitly by the
owner on 2026-09-22. Production uses JSON-object output with local schema checks,
`AI_REASONING_EFFORT=none`, latency-prioritized OpenRouter routing, and required
parameter support. On the ordinary OpenRouter adapter, `none` sends
`"reasoning": {"enabled": false}`, not `"effort": "none"`. Other configured
efforts are forwarded unchanged; an unspecified effort omits `reasoning` and
preserves the model/provider default. Non-OpenRouter adapters remain unchanged
and do not receive these OpenRouter-only fields. Disabling reasoning on a model
that supports disabling protects the bounded visible-output allowance;
`exclude: true` would only hide reasoning, not prevent its token use or billing.
The independent whole-answer review remains mandatory.
See the official [reasoning controls and metadata semantics](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).

The gateway's global effort enum is not a per-model compatibility guarantee.
Unauthenticated [model metadata](https://openrouter.ai/api/v1/models), observed
on 2026-10-04, reports this DeepSeek model with `mandatory: false`,
`default_enabled: true`, `default_effort: "high"`, and supported efforts
`["max", "high", "low"]` (not `"none"`). Unspecified reasoning therefore does
not mean disabled. Mandatory-reasoning models cannot satisfy this disable
configuration. Endpoint [supported parameters](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4.1-flash/endpoints)
must also cover the requested response format. The ordinary router retains
latency sorting and fallback routing: neither metadata nor a synthetic HTTP
smoke certifies a particular live provider's output, cost, or latency. The
private release guard's separate pinned Morph admission and counted journal
are not certification of this ordinary routing path.

The no-paid ordinary-router regression is
`apps/api/app/tests/test_router_reasoning_http.py`. It exercises the production
HTTP route, isolated SQLite and dedicated local Redis, the ordinary adapter's
outgoing provider request, structured responses and independent review,
committed replay, disabled providers and controlled provider failures.
The only replaced boundary is provider transport; responses are explicitly
synthetic. Set `KNICKSIQ_ROUTER_ARTIFACT_DIR` to a **fresh** private directory
per run to retain each request/response, exact outgoing payload, synthetic
model/provider/usage evidence, replay and monthly-ledger observations.
Use `ENVIRONMENT=production`, `KNICKSIQ_POSTGRES_TEST=0`, empty live credentials
and `REDIS_URL`, and run that HTTP test file with JUnit output. These regressions
do not replace any original release quality, budget, workload or load gate.

The production application cutoff is now $2, matching the owner’s available
credit; the original $8 default was not increased.

DeepSeek passed Action, ProposedAnswer and AnswerReview capability probes and
produced validated discovery answers against the active archive. These smoke
checks are not a completed release evaluation: repeated six-turn completion,
held-out human reviewer calibration, Recall@5 and warm p95 gates remain unproven.
Earlier NVIDIA and Nex probe artifacts are historical, not evidence for DeepSeek.

Development conversations and a separate held-out reviewer challenge draft live
under `app/evaluation/analyst-fixtures/`. Draft expected verdicts are explicitly
marked `human_reviewed: false`; they must be reviewed by a person before they can
satisfy the calibration gate. The held-out set includes causal claims hidden in
otherwise correct prose, hedged causation, subject/sign/scope swaps, retrieval
as a denominator, extreme-selection overclaims and injected source instructions.
