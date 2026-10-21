# Evidence-led analyst implementation

The analyst is the launch answer path: `POST /analysis/query` with
`ANALYST_EVIDENCE_LOOP_ENABLED=true` and `ANALYSIS_ANSWER_MODE=llm_primary`. The code default for
the loop is false, so local processes stay model-free until enabled. The intended launch
configuration is stated once in
[the release checklist](release-checklist.md#intended-launch-configuration). Other documents link
there instead of restating it.

The loop is one bounded orchestrator. It allows two tool rounds, three tool calls per round and
six model calls, including malformed output. Normal lookup uses choose, write, review; a prior
evidence explanation uses write, review; repairs reserve capacity for both calls. Replies remain
buffered. No prompt logging is introduced.

## Tools

Nine tools are registered in `analyst_tool_registry.py`. The prompt tool list, the `ToolCall.name`
Literal, dispatch, capabilities and fallback recovery all derive from that tuple.

| Tool | Answers |
| --- | --- |
| `get_player_stats` | Player box-score metrics as totals or per-game averages over a resolved window. |
| `get_team_stats` | Knicks wins, losses, points and margin over a population. |
| `compare_windows` | Two player populations compared on one metric. |
| `discover_facts` | Observed facts and narrative leads; leads the prompt. |
| `search_archive` | Narrative examples, reports and play-by-play evidence. |
| `get_evidence` | Expands returned references without adding a population. |
| `get_game_flow` | Runs, lead changes, comebacks, lost leads, clutch windows and period net. |
| `get_team_splits` | Home/road, phase and opponent splits. |
| `get_period_scoring` | Quarter, half, overtime and per-game period scoring for both teams. |

Capabilities are derived: a tool with `supports_periods` adds period scores and play-by-play
events to the model-facing data list. Quarter, period, play-by-play and split questions are
answerable. Dispatch names the period tools when a full-game tool cannot serve a period scope.

## Claims, prompt and reviewer

`evidence_contracts.py` defines the versioned contracts. Prompt version is `analyst-balanced-v4`;
validator version is `whole-answer-v2`. Claim IDs hash the release, definitions, calculation,
subject, scope, value and provenance. The writer can reference IDs and request rounding; it cannot
overwrite claims. Analytics read the complete applicable release population. Zero-minute player
rows are excluded from appearance denominators; missing rows are coverage gaps.

Discovery starts with observed box scores and the existing catalog, recomputed from complete
release rows under the existing eligibility policies. Catalog leaders retain the complete
qualifier population. Recent comparisons have distinct recent and prior claims, denominators and
source windows. Committed responses alone advance novelty state.

The reviewer receives a fresh context with the proposed answer, backend claims, selected receipts,
capabilities and interpretation policy. The backend owns the sentence spans and requires one
verdict per span in order. Before the model call, deterministic checks run:

- every number in the answer must match a supplied claim value within rounding tolerance, a
  receipt or a curated capability number;
- numbers from the question are accepted only in decline, coverage, date-window or clarification
  spans where they are criteria, not asserted facts;
- identifier hashes and game ids are never whitelisted.

Malformed, incomplete, unknown and unsupported verdicts fail closed. A malformed review response
is retried once, then the turn falls back. A supported verdict is authoritative for its span. The
reviewer is not proof of truth; human calibration remains a release gate.

## Model input, prefetch and latency

`ANALYST_REASONING_EFFORT=none` is the default and applies to every analyst call.
`AI_REASONING_EFFORT=none` is also the default. Without this setting the provider reasons at high
effort, spends the completion budget before any JSON and returns empty or truncated content.

Token caps: review 3,000 output tokens, answer 1,600 output tokens, planning action 600 tokens
with a 3,600-byte action guard. The analyst input budget is 16,000 UTF-8 bytes
(`ANALYST_INPUT_TOKENS`); measured JSON runs 3.5 to 3.9 bytes per prompt token. The 70-question
A/B in `docs/release-evidence/llm-primary-20261021/final/README.md` chose it over 8,000: honest
passes rose from 27/70 to 38/70 in both trials and dropped claims fell from 8.2 to 2.2 per
question. p95 latency rose from 6.2 s to 7.6 s and mean cost from $0.0011 to $0.0020 per question.
Payloads still reach p95 15,557 bytes, so the budget remains the binding constraint.
Input packing drops whole records and preserves their server-side references. Large claims are
omitted, never truncated. UTF-8 bytes bound input conservatively. Review packing drops eligibility
policy and generic coverage caveats before aborting a turn; values, subjects, scope, windows,
denominators and receipts remain.

`ANALYST_PREFETCH_ENABLED` defaults to true. Deterministic prefetch runs the one tool a clear
question already requires before the first model call: `discover_facts` for narrative, turning
point and single-player questions, `get_team_stats` for resolved team record or window questions,
and `get_player_stats` for a single-player average with a resolved window. It skips
clarifications, live, future, injury and trade questions, multi-player comparisons,
player-versus-opponent questions, comparative metric questions and two-population comparisons.
Prefetch passes only a question and aggregation; the backend applies the resolved scope.
Prefetched tools count toward the tool and model call bounds.

Measured on 40 questions on the final tree: p50 2,290 ms, p95 4,608 ms, 2.5 provider calls per
question, 35/40 validated. The base tree was p50 3,117 ms and p95 4,370 ms at 2.83 calls. The
p95 gate of four seconds is not met, so promotion needs an owner exception or further work.
Full stage tables and artifacts are in
`release-evidence/llm-primary-20261021/latency/README.md`.

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
`llm_validated=false`, `refused=true`, `degraded=false`, no citations and the refusal warning. A
deterministic fallback sets it when the question asks for live or current state.
`ask_clarification` is not a refusal. `refused=true` never means the request failed; the browser
renders a decline, not an error.

## Season phase policy

Season-level records and stats default to the regular season. The answer must state the phase, for
example "53-29 in the regular season". The all-phase record, 69-32, appears only when the question
names overall, including playoffs or all phases. Opponent matchups span every phase and carry
regular-season and playoff breakdowns. Game-flow and period claims name their phase. An explicit
phase in the question wins. The rule lives in `query_policy.py` and `query_resolution.py`; the
fallback and team tools apply the same population.

## Budget

The configured monthly cutoff is $2. Reservations, cutoff checks and settlement are atomic. The
expected path reserves before generation; investigation and repair reserve remaining capacity
before execution. Reported provider cost settles actual usage. A billed provider response that the
adapter rejects settles at the provider's reported cost, not at the flat reservation. A call with
no HTTP response keeps the reservation policy. This removes the phantom charge measured on empty
or truncated responses.

An absent `ai-budget:YYYY-MM` key blocks all model paths, including legacy callers. Do not
initialize a lost production ledger to zero. Reconcile provider billing, previous reservations and
uncertain in-flight requests, then restore a conservative total through administrator-controlled
Redis access. The ledger has no automatic expiry. A new month also requires reconciliation. Shadow
uses the same ledger.

At $2 the measured capacity is about 1,413 questions per month on current routing, at a mean of
$0.001415 per question. It is highly route dependent: OpenRouter routing is unpinned and the same
model spans an 8.8x price range across endpoints. Current routing gives about 1,200 to 1,400
questions per month; pinning the cheapest endpoint would give about 10,000 to 12,000. Category
breakdowns and the accounting reconciliation are in
`release-evidence/llm-primary-20261021/cost/README.md`.

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

Run `uv run --package knicksiq-api python -m app.evaluation.analyst_probe` against the configured
provider. `ANALYST_PROVIDER_FORMAT=json_schema` enables strict schema and OpenRouter
`require_parameters`; the explicit default `json_object` still requires local schema validation.
No model substitution occurs.

The live harness scores the committed questions with the honest scorer:

```sh
uv run --package knicksiq-api python tools/release/analyst_live_e2e.py \
  --per-category 2 --out docs/release-evidence/analyst-live/latest.json
```

The scorer reads structure first, then cited claim values. It records `refused`, `degraded`,
`llm_validated` and warning fallbacks before any phrase check. A refused answer counts as a pass
only for an unanswerable question. Numbers in an answer must appear in a cited claim or receipt.
See `docs/evaluation.md` and the `scoring` evidence directory.

The production model is `deepseek/deepseek-v4.1-flash`, selected by the owner on 2026-09-22.
Production uses JSON-object output with local schema checks, `ANALYST_REASONING_EFFORT=none`,
`AI_REASONING_EFFORT=none`, latency-prioritized OpenRouter routing and required parameter support.
The independent whole-answer review remains mandatory. The application cutoff is $2.

DeepSeek passed the Action, ProposedAnswer and AnswerReview capability probes. The independent SQL
audit found zero incorrect and zero unsupported figures on the audited responses. The honest
held-out baseline was 5/60 before the correctness fixes, and the full set has not been re-measured
live since. The release record stays blocked and owner sign-off is required. Existing release
approvals remain required; this implementation does not promote or deploy itself.
