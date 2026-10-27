# Bounded real-provider verification — approval required

Status: prepared, not authorized or run. Candidate: `e003db2d7f179c8d490d90155f260ec0eeb31620`.

## Fixed configuration and limits

Read-only Render observation confirms OpenRouter at `https://openrouter.ai/api/v1`, model **`deepseek/deepseek-v4.1-flash`**, `json_object`, temperature 0, reasoning `none`, request timeout 20 seconds. Keep the existing model allowlist and **$2 monthly cutoff**. The candidate adapter allows routing between providers for the same model; no alternate model is authorized. Local `.env` names a different model and must not be inherited accidentally.

Proposed authorization ceiling: **9 application HTTP completion requests, $0.10 total additional spend, one run, no repeat runs**. Three direct contract probes plus one analyst turn with at most six model calls. Calls are sequential; no concurrency. Each direct probe has at most 1,200 input and 1,200 output tokens; the analyst turn keeps existing input/evidence bounds (8,000/6,000 tokens), output limits (600 or 1,200), two tool rounds and 30-second overall deadline. Direct requests stop at 20 seconds; complete sequence is limited to 90 seconds. No transport retry; bounded proposal/review/repair calls within the analyst turn count toward the six-call ceiling.

**The existing $0.01 reservation is accounting, not a provider-enforced per-call price cap.** Before any paid request, verify current provider pricing and a conservative token-based worst-case charge for the complete request (including reasoning or other billable tokens). Require worst-case cost <= $0.01 per request and <= remaining run allowance. Include unknown/timed-out charges at their worst-case reservation. If the adapter cannot prove these bounds, do not run it; prepare a local verification wrapper enforcing them first, with no application-source changes. Do not assume a reservation makes a $0.10 hard cap effective.

Read the existing monthly ledger and outstanding reservations before execution. A missing/unreconciled ledger, unavailable Redis, insufficient remaining monthly allowance, or unverifiable provider price prevents execution. Do not initialize/reset the ledger, raise spending limits, create keys, change providers, or disable budget controls to make the probe pass. No paid test is authorized by this document or by the earlier unanswered one-check request.

## Cases

| Case | Expected result | Maximum requests |
| --- | --- | ---: |
| Action contract | Real provider returns a valid `Action` requesting an allowlisted fact tool for synthetic archive data. | 1 |
| ProposedAnswer contract | Real provider returns valid clarification JSON (“Which player?”), no fabricated claims/references. | 1 |
| AnswerReview contract | Real provider returns a valid review of that synthetic clarification. | 1 |
| Actual candidate analyst turn: “What were their wins and losses?” | Isolated two-win/one-loss database and local session state; real provider proposes/reviews an answer with exactly 2 wins, 1 loss, correct fixture population and genuine fixture citations. Capture provider model/request metadata, tools, validation and bounded latency. | 6 |

Run only the pinned candidate in an isolated local process. Use synthetic test data for provider payloads; do not upload the production export, rollback snapshot, report bundle, logs, or evaluation package. Public fixture evidence emitted through allowlisted tools is sufficient for this bounded provider integration check. Keep test storage/session state isolated, but charge through the real reconciled monthly budget controls. No provider traffic from ordinary CI, full evaluation, load testing, or failure injection is included.

## Stop and classify honestly

Stop the run immediately on an HTTP/auth/rate-limit error, malformed schema, unexpected model, timeout/cancellation, budget denial, unavailable ledger, missing usage/cost, evidence mismatch, unavailable deterministic retrieval, exceeded bound, or failed case. Do not retry or proceed to later cases. Unknown cost retains its reservation. A fallback can prove recovery safety but fails the live-provider-success criterion. `budget_unavailable`, a mock adapter, empty response, and fixture-only success are not passing real-provider evidence.

A pass requires actual provider responses, matching model metadata, all contract validations and the correctly cited analyst answer; save a local sanitized result with candidate, fixture identity, request counts, usage/cost, latency, route, degraded/validated state, and pass/fail per case. Never log credentials, session tokens, full prompts, or raw provider responses. This verifies bounded capability/integration on synthetic data; it does not close the 120-case retrieval evaluation or establish broad model quality.

Approval wording: “Authorize this plan for `e003db2`, existing `deepseek/deepseek-v4.1-flash`, maximum 9 requests and $0.10 additional cost, subject to all preflight bounds and stop conditions.” Changes to case scope, model, caps or retries require a new explicit authorization. This approval would not authorize deployment, content activation, remote staging, or publication.
