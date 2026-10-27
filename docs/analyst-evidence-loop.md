# Evidence-led analyst implementation

The analyst is the launch answer path: `POST /analysis/query` with
`ANALYST_EVIDENCE_LOOP_ENABLED=true` and `ANALYSIS_ANSWER_MODE=llm_primary`. The intended launch
configuration is stated once in
[the release checklist](release-checklist.md#intended-launch-configuration). Other documents link
there instead of restating it.

The opt-in route replaces the discovery early return and legacy planner/generator chain with one
bounded orchestrator. It uses the existing configured model, controlled tools, immutable backend
claims, a separate whole-answer reviewer, and one optional revision/re-review. The default local
default remains **false**. The production Blueprint enables the loop and `llm_primary` following
the owner’s explicit production activation request. `ANALYSIS_ANSWER_MODE=deterministic` provides
immediate model-free rollback with the flag enabled. `shadow` exercises the same metered loop and
delivers facts.

The loop allows two tool rounds, three tool calls per round and six model calls, including
malformed output. Normal lookup uses choose, write, review; a prior evidence explanation uses
write, review; repairs reserve capacity for both calls. Replies remain buffered. No prompt logging
is introduced.

## Tools

Eleven tools are registered in `analyst_tool_registry.py`. The prompt tool list, the `ToolCall.name`
Literal, dispatch, capabilities and fallback recovery all derive from that tuple.

| Tool | Answers |
| --- | --- |
| `get_player_stats` | Player box-score metrics as totals or per-game averages over a resolved window. |
| `get_team_stats` | Knicks wins, losses, points and margin over a population. |
| `compare_windows` | Two player populations compared on one metric. |
| `discover_facts` | Observed facts and narrative leads; leads the prompt. |
| `search_archive` | Narrative examples, reports and play-by-play evidence. |
| `get_evidence` | Expands returned references without adding a population. |
| `find_player_games` | Counts a player's games meeting an explicit per-game stat threshold and lists the matching archived games. |
| `get_game_narrative` | Canonical game narratives, tied game stories, comebacks and lost leads selected from the archive. |
| `get_game_flow` | Runs, lead changes, comebacks, lost leads, clutch windows and period net. |
| `get_team_splits` | Home/road, phase and opponent splits. |
| `get_period_scoring` | Quarter, half, overtime and per-game period scoring for both teams. |

Capabilities are derived: a tool with `supports_periods` adds period scores and play-by-play
events to the model-facing data list. Quarter, period, play-by-play and split questions are
answerable. Dispatch names the period tools when a full-game tool cannot serve a period scope.

`ResolvedQuery` owns the requested statistics and game population. `requested_metrics` and
`requested_aggregations` preserve compound requests. The scalar `metric` and `aggregation`
identify an unambiguous selection, not an arbitrary first member. Dispatch keeps single
selections authoritative and restricts compound tool calls to a requested member. Session
scope retains both sets for follow-ups. Unspecified fields remain model-selectable.

## Contracts and limitations

`evidence_contracts.py` defines the versioned public/internal contracts. Claim IDs
hash the release, definitions, calculation, subject, scope, value and provenance.
The writer can reference IDs and request rounding; it cannot overwrite claims.
Analytics read the complete applicable release population. Zero-minute player rows
are excluded from appearance denominators; missing rows are coverage gaps.
Team score-threshold counts compare each game in the resolved population with the
shared `StatThreshold` semantics and return `games:count`, not a season score sum.
Player leader calculations use canonical Knicks box-score rows inside that same
scope. Explicit single-game highs rank individual appearances, preserve every tie,
and retain evidence for the complete candidate population; scoped leaders otherwise
sum each player's rows only within the requested window.

Canonical discovery verifies its complete SQL-bound source corpus before lexical
retrieval. Integrity preparation uses the configured investigation budget (20 seconds
in staging), inside the unchanged 30-second HTTP request deadline. The four-second
local retrieval deadline then covers lexical search, ranking and receipt admission,
not source transfer and integrity verification. No source check is cached or skipped;
invalid proof and slow lexical retrieval still return dependency failure.

Canonical snapshot preparation serializes each complete SQL row once and reuses
those exact bytes for sorting and streaming the snapshot hash. It does not cache
snapshots or omit rows. Player-name resolution skips impossible substring matches
before applying the existing word-boundary matcher; positive matches and ambiguity
rules are unchanged. Lexical retrieval constructs its source-unit table once and
applies the existing SQL match/rank expressions to that table, retaining the same
filters, tie ordering, limits and complete source metadata.

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

The reviewer instruction names the native assertion types explicitly:
`coverage` for generic archive-completeness caveats, `conversational` for
nonfactual clarification, `factual` for facts and `interpretation` for inference.
Supported factual and interpretation spans still require admitted supporting
claims or evidence; coverage and conversational spans may omit those IDs.
An unsupported factual span is not relabelled after generation. Captured
classification replays diagnose failures but do not qualify a live answer.

Input packing admits or drops whole records and preserves their server-side
references. At each mandatory-context, claim-group and evidence boundary, UTF-8
bytes account for the actual system instructions, serialized user payload and,
in `json_schema` mode, the actual scoped provider schema. The 16,000-byte input
cap and 6,000-byte evidence allowance apply. Strict mode retains only the
protocol title in the user's `schema` field; validation constraints appear once,
in the provider schema. Nonsemantic schema titles, descriptions and defaults are
compacted without changing native allowed values, reference enums, exact review
boundaries or the two-follow-up limit. JSON-object mode carries the same scoped
wire schema in its user payload and requires local validation. This conservative bound underfills context compared
with a model-specific tokenizer. Large records are never truncated; requested
record pairs and selected narrative/scalar game sets are indivisible and fall
back completely if they cannot fit. Investigation allows two rounds, three tools
per round and six model calls total, including malformed output. Normal lookup
uses choose/write/review; prior-evidence explanation uses write/review. Repairs
require capacity and time for both calls. Replies remain buffered. No prompt
logging is introduced.

Prompt version `analyst-balanced-v6` uses lossless shared claim/evidence contexts:
each record inherits common metadata and explicitly overrides differences,
including null, false, zero and empty collections. Exact common statement parts
and repeated object-array column names are factored only when they save bytes.
Table descriptors retain ordered columns, common fields and every typed row value;
the immutable native registry, provenance IDs and public claim JSON are unchanged.
Repeated provenance lists factor only a common string prefix; concatenating that
prefix with every ordered suffix restores every complete source ID.
Selected record, narrative, profile and baseline claim groups remain complete.

Writer payloads with fixed backend coverage requirements carry
`required_claim_indexes`: one domain of supplied claim indexes per existing
requirement. Output `claims` is a closed object keyed by requirement ordinal
(`"0"`, `"1"`, …), not by claim index. Each required scalar integer selects a
row of the sealed `claim_uses` table: `[claim index, precision]`, in supplied
claim order, exact/null first and numeric precisions 0–3 next. The backend restores
only the selected native ID, complete typed value and correlated precision.
A score object is one exact choice; prose or two margin choices cannot fill its slot.

The shared requirement computation preserves existing record/profile/team-group
coverage and every selected/tied statistical-extreme metric/game predicate.
Alternatives satisfying the same predicate share one slot. Optional supplied
context is not mandatory: `related_claim_indexes`, when nonempty and allowed,
seals a separate `related_claims` choice array which may be empty. Its domain
excludes every required-domain claim ID. Statistical extrema retain their exact
declared-count policy and have no related tail. Questions without fixed requirements,
including leader existence and textual narratives, retain the native ClaimUse
array wire and their existing post-decode acceptance rules.

Missing/extra/wrong slots, noninteger choices (including booleans and integral
floats), invented choices, duplicate claim selections and duplicate JSON keys
fail closed before native parsing or independent review. Neither decoding nor
scripted-fixture encoding fills missing selections or repairs invalid proposals.
`payload_claim_uses` expands the whole choice table in keyed mode; scripted native
writers must select one actual use per claim, not copy all precision alternatives.
Repair `proposed_answer.claim_uses` retains the original declared uses in order,
including a bad duplicated margin, rather than converting them into mandatory slots.
Conflicting values on repeated declared IDs additionally use declared-use ordinal
overrides, so even malformed historical repair proposals restore losslessly.

Reviewer proposals, complete native values, provenance and literal review spans
remain unchanged. No required-slot metadata is sent to review. Compact table values
and `span_index` / `follow_up_index` references are decoded before existing native
validation in both the analyst and counted verification adapters. Review order,
coverage, supporting IDs and independent instructions are unchanged. All answer
properties are explicitly required in the scoped writer/provider schema.
Answer text contains the requested answer and limitations, not packet metadata,
schemas, IDs or packing instructions; suggestions belong only in their dedicated
array. The answer output cap is 1,600 tokens and the review cap is 3,000.
Malformed or length-terminated JSON is never treated as a validated model answer.

Planning, writer and reviewer instructions remove redundant wording to leave room
for complete claim bundles within the existing byte budget. They retain every
tool-selection, leader-completeness, value/type/precision, source-ID, interpretation,
mixed-scope and follow-up rule. Whole-span review still checks every subject,
metric/value, unit, sign, denominator, filter, window, baseline, release, rounding
and citation; suggestions are reviewed independently of the answer. Prompt wording
must not crowd admitted evidence into an empty-claims tool loop.

Whole optional source receipts retain the original admission policy: a complete
immutable claim may support a span without its receipt, but explicitly cited
receipts must fit in full. No source text or required fact is truncated, and no
input, evidence, model-call or deadline allowance is raised.

## Deterministic requested statistics

The evidence-loop route calculates requested leaders, home/away and win/loss
comparisons, monthly records, first/last team-game records, team quarter scoring,
player recent-versus-season averages, and single-game player profiles from the
active release. Comparison groups reuse `team_scope.comparison_groups`.
Bench scoring divides nonstarter points by team games; shooting percentages
divide total makes by total attempts. Player averages use observed appearances,
not team games. Leader ties and tied selected games remain complete.
Player profiles for a defined game extreme use only every tied selected game,
not the whole comparison population. Player-free score comparisons retain the
complete eligible population; ordinary player aggregates retain the user's
requested population.
The orchestrator advertises `get_team_stats` for team-wide player scoring/statistic
leaders over the complete requested team-game population, including ties.
`discover_facts` supplies candidate facts, not an authoritative substitute for a
requested multi-game leader calculation. The existing backend calculation and
complete-population validator remain responsible for this distinction.
Native preparation and admission share `population_facts.is_player_leader_request`,
including non-points leaders and single-game highs. The complete requested
statistic is a mandatory claim group; a supported but nonresponsive player total
cannot replace it. Validation distinguishes `:single_game_high` from `:leaders`
and retains the exact requested game population.

`find_player_games` handles a named player's per-game threshold question from
the complete scoped appearance population, including postseason. It uses the
canonical stat registry for points, rebounds, assists, steals, blocks and threes
made; operator and cutoff are preserved in backend claims, and each matching
game is returned with its player box-score evidence.


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
Model payloads omit unbound (null) optional scope descriptors. Backend scope,
non-null filters, complete populations and mandatory claims remain unchanged.

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
plus comparison inputs when needed.
An unresolved conversational game reference stops canonical discovery before
archive-unit construction or retrieval. It clarifies with no candidate or returned
evidence IDs and no model call, including in primary and sampled-shadow modes.
Shared parsing helpers live in `query_text`, `query_names`, `query_dates`, `query_policy` and
`query_game_scope`; `query_resolution` does not re-export them. `query_parsing` remains only for
main-side archive-unit, threshold-game and population-fact modules.

Scoped ambiguous game questions offer actual archived dates without asserting
a matching-game count. Explicit win, loss, closest, and biggest-win conditions
use final scores. A lost lead requires the opponent to lead after a Knicks lead;
a comeback requires the Knicks to lead after trailing; an erased deficit may
include a later tie. These lead/tie definitions are draft semantics pending owner review.
Missing, nonmonotonic, or unreconciled scoreboards trigger an unverified-data
clarification instead of being counted as matches or no matches.
For a one-fit lead-change question, the canonical narrative carries the final
score and the first verified transition pair witnessing each requested condition,
not every scoreboard transition. Its prepared claim evidence is prioritized over
unrelated retrieval receipts so review can retain all sources the writer cites.

When the evidence loop is disabled, the deterministic query route resolves a
named-opponent lead condition before generic retrieval. One verified fit returns
the canonical narrative claim and its provenance without asserting an unobserved
cause; the writer and reviewer are not invoked.
Ambiguous scoring sequences ask for both the game and the run
measure/time-window definition. A request for two games does not silently expand
to all matching games.

## Deterministic prefetch

`ANALYST_PREFETCH_ENABLED` defaults to true. Deterministic prefetch runs the tools a clear
question requires before the first model call. Simple single-player compound requests fetch
each requested metric and aggregation within the existing six-tool limit. Fallback retains
all requested statistics already fetched, rather than treating a compound metric as points.
Other routes use `discover_facts` for narrative and single-player facts, `get_team_stats` for
team records and `get_player_stats` for single-player aggregates. Prefetch skips
clarifications, live, future, injury and trade questions, multi-player comparisons,
player-versus-opponent questions, comparative metric questions and two-population comparisons.
Prefetch passes the current question and selected metric and aggregation. Dispatch applies scope.
Prefetched tools count toward the tool and model call bounds.

## Answer evidence selection and repair

`answer_evidence.py` selects the answer's declared claims, their baseline claims and supporting
receipts, plus explicitly cited receipts. Validation, reviewer input and delivery use that
selection. A factual statement cannot borrow a different, undeclared claim to pass the numeric
check. Unknown or unsupplied references fail before review.

Player coverage text describes non-appearances and missing data without internal game ids.
The reviewer receives those coverage limitations with the selected claim. Numeric validation
does not whitelist identifiers or arbitrary numbers from coverage prose.

The backend owns the sentence spans and requires one verdict per span in order. Before the model
call, deterministic checks run:

- every number in the answer must match a selected claim value within rounding tolerance, a
  selected receipt or a curated capability number;
- numbers from the question are accepted only in decline, coverage, date-window or clarification
  spans where they are criteria, not asserted facts;
- identifier hashes and game ids are never whitelisted.

Malformed review output is retried once, then the turn falls back. A supported verdict is
authoritative for its span. The reviewer is not proof of truth; human calibration remains a
release gate.

Repair requests use a separate prompt matching the flat `ProposedAnswer` schema. They return
`text`, `claims`, `evidence_ids`, `fact_ids` and `follow_up_questions`, without an action or
answer wrapper. Repairs cannot investigate or change the requested metric or aggregation.

## Refusals and the `refused` flag

Two layers decide a refusal.

The pre-model gate is a typed table in `analysis_policy.py`. It refuses only text with no archive
reading, before any provider call:

| Category | Catches |
| --- | --- |
| `instruction_override` | Ignoring or revealing prompts and instructions, jailbreak, persona changes. |
| `wagering` | Bets, wagers, parlays, moneylines, sportsbooks, spreads and betting lines. |
| `out_of_archive_date` | 2027 to 2099 years and 2026-07 through 2026-12 dates. |

Live, injury, trade, prediction and bare `odds` words are not pre-model refusals. Fans use them
with archive meanings. Those questions reach the analyst, which answers the archive part, declines
or explains coverage. The same applies to a question that mixes an archive request with one of the
ambiguous words.

`refused` is true when the delivered answer declines or explains coverage. A validated model
refusal sets it from the `decline` or `explain_coverage` action and returns
`llm_validated=true`, `refused=true`, `degraded=false`. A pre-model refusal returns
`llm_validated=false`, `refused=true`, `degraded=false`, no citations and the refusal warning.
A mixed archive/live question can still deliver supported archive facts without refusing the turn.
`ask_clarification` is not a refusal. `refused=true` never means the request failed; the browser
renders a decline, not an error.

## Season phase policy

Season-level records and stats preserve the resolved population: without an explicit or inherited
phase restriction, they include every archived phase. An explicit phase in the question wins;
an elliptical follow-up retains its accepted phase until the user widens the scope. Answers and
claims state their population, and fallback and team tools use that same population. Phase
resolution lives in `query_policy.py`, `query_resolution.py` and `query_game_scope.py`.

## Session API

Send previous user and assistant messages as context, plus:

```json
{"question":"Give me an interesting stat", "turn_id":"client-generated-uuid",
 "session_token":null, "expected_revision":0}
```

Replies preserve `answer` and `citations` and add `follow_up_questions` (zero to two),
`session_token`, `revision`, `session_expires_at`, `state_committed`, `llm_validated`, `refused`,
`degraded` and `warnings`. The opaque token is a bearer secret; do not log it. Redis owns subject
and scope origins, intent, claims and receipts, delivered facts, families, release and revision.
Client `conversation_state` is ignored by this route. Active release identity is pinned and prior
references are revalidated against the newly resolved scope. A changed release clears old
evidence.

Lua scripts serialize turns with an owner-checked lease, check revisions, and atomically commit
the response and state. Identical turn retries replay the exact committed reply, including
first-turn retries. Different input under the same ID, stale revisions and concurrent execution
return 409. Sessions and replay records expire after 24 hours of inactivity. Redis loss gives an
explicitly stateless factual response; a failed commit never claims a committed revision. The
browser retains turn IDs for retry and prevents synchronous duplicate submission.

Greetings and pre-model refusals use the same session revision, replay and commit path. Their
reply is committed without changing the prior topic or scope and without a model call. A
following pronoun or metric question therefore still refers to the earlier archive question.

Both chat surfaces share a transcript that remains fully visible. Each request sends the ten
previous individual messages, excluding the current question. The API keeps at least a UTF-8-safe
opening excerpt of every retained message, then restores newest detail within a 2,000-byte
serialized history allowance. Server session state separately retains topic, scope and verified
claims. Transcript text has no evidence authority and is absent from the independent answer
reviewer. The writer returns short answers by default and can offer two follow-up questions in the
same call. The reviewer checks suggestions; rejected suggestions are omitted while a valid answer
survives.

The browser stores a versioned transcript, session identity, expiry, archive version and exact
pending turn in `sessionStorage`. Reload exposes Retry for an interrupted turn. New chat aborts
in-flight work and clears the active conversation. A 409 with `session_expired` starts a visible
new-conversation boundary, keeps older messages readable and leaves the submitted question ready
for Retry or editing. Archive changes invalidate the old context. Storage failure leaves the
in-memory chat usable and displays a refresh-recovery notice.

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
schema bytes at dispatch, confirm every input is at most 16000 UTF-8 bytes, and
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

The live harness scores the committed questions with the honest scorer:

```sh
uv run --package knicksiq-api python tools/release/analyst_live_e2e.py \
  --per-category 2 --out docs/release-evidence/analyst-live/latest.json
```

The scorer reads structure first, then cited claim values. It records `refused`, `degraded`,
`llm_validated` and warning fallbacks before any phrase check. A refused answer counts as a pass
only for an unanswerable question. Numbers in an answer must appear in a cited claim or receipt.
See `docs/evaluation.md` and the `scoring` evidence directory.

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

The intended deployment configuration uses OpenCode Go. The writer is
`deepseek-v4.1-flash` over Chat Completions. `ANALYST_REVIEW_MODEL=gpt-6-luna`
selects the independent whole-answer reviewer over Responses through
`AI_MODEL_PROTOCOLS`. It is not a retrieval reranker. Set the Go credential in
`AI_API_KEY`; no client credential is exposed.

The blueprint and library defaults allow 1,600 output tokens for writing and
3,000 for review. The input cap is 16,000 UTF-8 bytes with a 6,000-byte evidence
allowance; call-count and deadline limits are unchanged. Each adapter sends a random
`x-opencode-session` identifier unrelated to the user's bearer session token.
`AI_MODEL_PRICES` supplies estimated USD-per-million input and output token rates
when the subscription host omits per-call cost. Those estimates are not billing
receipts. The existing application cutoff still limits reserved usage.

The following OpenRouter notes describe the earlier deployment and the frozen
counted evaluator. Ordinary OpenRouter routing still supports its existing pinned
route and price caps. `none` sends `"reasoning": {"enabled": false}`.
On Go Chat Completions, effort is a top-level `reasoning_effort`; Responses uses
`reasoning.effort`. Automatic deployment remains disabled.

The frozen original120 collector remains bound to its authorized OpenRouter
model, key, pricing and blueprint. It fails closed after the host change and
cannot certify this Go configuration. New provider-compatible release admission
and quality evidence are prerequisites for public-release certification.

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

### Native comparison and population authority

Extreme-game claims retain the eligible comparison population before selecting
the extreme and every tied game. Their immutable eligibility records include
the comparison definition, eligible game IDs, selected tied IDs, sample size and
compared archive phases. Supporting calculation receipts retain every eligible
game's source receipt; a selected game's phase is not the comparison universe.
The same comparative score receipt supports its derived final margin.

Native narrative preparation calls `resolve_query(select_extrema=False)` so
an earlier biggest-win or best-defensive target selection cannot shrink that
comparison population. Ordinary archive retrieval and conversation references
still resolve the selected targets.

Computational `get_player_stats`, `get_team_stats` and `compare_windows` calls
retain the user's temporal/game population, including unrestricted `None` and
empty defaults. A model cannot silently substitute regular-season, opponent or
date restrictions. Retrieval can still narrow examples; explicit comparison
baseline questions retain their separate canonical resolution.

Failure-first HTTP regressions exercise real archive rows, isolated Redis,
delivered citations and committed replay. They verify complete comparison and
tie-source coverage, three unauthorized population restrictions, and an
explicit-phase control. Their repeatable private artifacts are in
`extreme-comparison-and-player-scope-regression/`: the consumer-visible before
run failed four cases and passed the control; the integrated after run passed
all five, including the existing twenty requested-scope scenarios.
Provider responses in the population HTTP checks are scripted, not paid model
answers. These checks do not approve fresh DeepSeek answers or replace the
original primary120, semantic50, shadow120, load or restoration gates.
