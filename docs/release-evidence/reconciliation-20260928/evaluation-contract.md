# Evaluation contract reconciliation — not ready for final label approval

The original question file and label proposals are immutable. No final
quality run has been started. No expectation is learned from rehearsal output.
`expectation-review.json` contains all 120 original cases, their proposed typed
outcomes/facts, and a separate semantic target decision for each of the original
50 retrieval cases. Approval remains null; expectations are not yet frozen.

## Exact proposed scoring changes

Use a recorded per-case review protocol rather than the old phrase-matching
harness. The old harness cannot score these proposals correctly. It reads the
original top-level answerability, equates all nonanswers with refusal, assumes
canonical and runtime IDs match, and recomputes the semantic denominator from
answerability/route. No old-harness result will be presented as final metrics.

For each of 120 responses, retain candidate/content/expectation hashes, full
local response, elapsed time, exact requested context and turn/session identity,
ranked top-5/top-20 traces, and reviewer decisions with evidence. A review must
record actual disposition as answer, clarify, or refuse independently of
`degraded`, route and the legacy `refused` boolean. Budget failure is not a
correct refusal. A question asking for needed scope without unsupported factual
premises is clarification. A refusal says the request cannot be fulfilled from
the archive and explains why. Misclassifying either as the other fails.

For answer cases, review every stated assertion against the independently
proposed typed facts: subject, value, unit, scope, denominator/window, date,
release and canonical entity. Exact integers must match. Decimals must equal
the canonical value rounded to the displayed precision, with correct units.
Extra unsupported facts fail even when all requested numbers appear. Natural
paraphrases may pass only when all these fields agree; substring matching and
phrases learned from candidate output are disallowed. Reviewer decisions must
include the answer span and canonical fact IDs. Disagreements stay unresolved
and block aggregate passing metrics.

For citation scoring, resolve each runtime reference using the local restored
mapping and receipt contents. Do not strip prefixes and assume identity.
- Game receipts map release version + SQL game ID to the canonical NBA game.
- Player receipts additionally map SQL player ID to canonical NBA player ID;
  verify actual row values, player, game and release.
- `calculation:` receipts require the committed evidence record, source receipt
  expansion, independently checked arithmetic, denominator, filters and scope.
  A matching hash alone is insufficient; reject missing source receipts.
- Narrative/report/possession/vector references require verified candidate
  payloads, game identity, event boundaries and text. A report about a game is
  not proof of every claim about that game. Remote IDs must be remapped and
  reverified after staging; local IDs cannot be copied blindly.
- Team/period source rows are mapped to SQL identities but have no standalone
  evidence-loop receipt ID. Require the actual emitted evidence and its claim;
  do not fabricate one from the canonical prefix.

The local `runtime-mapping.json` verifies loaded SQL fields, not just bundle
references, for 3,867 unique source rows and all 4,160 label references. This
resolves local source identity only. It does not establish that a runtime
answer or citation is correct. Full runtime claim/citation grading remains
part of the final evaluations. Missing trace or receipt is a failure, not N/A.

## Fixed denominators and freeze

All 120 original questions remain. The proposal retains 58 answer, 53 clarify,
9 refuse cases, subject to owner adjudication. Numeric/entity/citation/paraphrase
metrics use the answer cases defined by the approved expectation file;
correct-abstention scores all expected clarify/refuse cases and requires the
exact outcome. Report clarification and refusal separately as well. Numeric,
entity and abstention gates remain 100%; citation and paraphrase remain >=95%.

Semantic Recall@5 remains an unweighted mean over the original 50 semantic
cases, including cases whose delivery expectation becomes clarify or whose
route changes. Each needs independent relevant evidence targets and ranked
traces. Unresolved targets block the metric and release. They are not assigned
passing abstention scores, omitted, or replaced by contextualized questions.
Do not silently equate a source population of 101 games with 101 independently
relevant top-5 retrieval targets. Relevant-document targets need review apart
from arithmetic source provenance. No threshold is reduced.

Before requesting final label approval: resolve every semantic target and
fact/outcome dispute in `expectation-review.json`, attach actual local
index-payload mapping and the reviewer protocol, and validate complete case
coverage. Then obtain approval bound to full hashes of questions, expectations,
protocol and mapping scope. Write a separate immutable freeze manifest and
approval artifact. Both final runs verify that manifest before and after
execution. Any expectation change invalidates the affected evaluation approval
and results; keep old artifacts under their original identity.

## Paid-call boundary and separate proposed budget

The 120-case service-disabled run has Qdrant, Redis and OpenRouter disabled,
with a hard provider-denial wrapper. Proposed paid-call budget: **0 requests,
$0**, no authorization for paid traffic needed. It still waits for frozen gold.

The service-enabled run must exercise genuine llm_primary session turns; the
old CLI omits turn IDs and can silently exercise only factual fallback. With
120 cases and at most six nested completion calls per turn, propose **720 total
completion requests, no extra transport retries, $0.50 aggregate**, subject to
an enforced conservative pre-call cost bound and the unchanged $2 monthly
cutoff. This is a proposal, not executable authorization or a demonstrated
price bound. If prices/token/reasoning bounds cannot fit, stop and present a
revised bound; never start by assuming reservations are actual costs. Include
all planner/reviewer/repair calls in the same aggregate cap. Prohibit extra
provider paths outside that counted wrapper. Use local cached embeddings so
retrieval incurs **0 paid embedding requests**. A cloud-inference-equivalent
run would need its own verified embedding cost bound before authorization.

The pre-promotion 120-turn shadow run at rate 0.1 is a separate stage: propose
at most **720** completion requests in the absolute worst case (sampling is
not a hard request cap), **$0.50 aggregate**, same pre-call price bound and
monthly cutoff. Record the deterministic selected sample count and reduce the
request cap to at most six times that count before requesting execution
approval. It cannot replace the primary or disabled evaluations. Synthetic
fixture sampling tests cost $0 and do not prove live quality.

Only the 9-request/$0.10 compatibility smoke is currently authorized. It stopped
before any completion call because the real monthly ledger was unreachable.
No additional paid evaluation is authorized or has been run.

## Trace collection limitation found during reconciliation

The evidence-loop response currently exposes model-stage timing, not the
`returned_evidence_ids` / `candidate_evidence_ids` fields consumed by the legacy
harness. The final local evaluation runner must capture actual lexical/dense
and fused ordering at the retrieval boundary, bound to each request. A case
that never retrieves has a missing trace; do not run a separate search and
pretend it was the analyst's retrieval. This remains an execution prerequisite,
not permission to change the semantic denominator. Local index construction
and point mapping are complete, but they do not close this trace requirement.

Owner decision in this chat: **Keep unresolved cases blocking release.** This
accepts continued blocking, not the labels, rubric, policy proposal or spending.
No final label approval is requested while targets remain unresolved.
