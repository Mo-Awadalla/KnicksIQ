# Evidence-led analyst implementation

The opt-in `ANALYST_EVIDENCE_LOOP_ENABLED=true` route replaces the discovery early
return and legacy planner/generator chain with one bounded orchestrator. It uses
the existing configured model, six controlled tools, immutable backend claims,
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

The tools return distinct statuses for ambiguity, empty matches, incomplete
coverage, unsupported scope, dependency failure and success. Search results are
examples, never season denominators. Qdrant failure does not disable SQL claims.
Causal language requires explicit supporting source material and attribution;
hedging, reviewed reports and connected events do not create blanket permission.

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

The production model is `deepseek/deepseek-v4.1-flash`, selected explicitly by the
owner on 2026-09-22. Production uses JSON-object output with local schema checks,
`AI_REASONING_EFFORT=none`, latency-prioritized OpenRouter routing, and required
parameter support. This keeps provider reasoning from consuming the bounded JSON
output allowance. The independent whole-answer review remains mandatory.
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
