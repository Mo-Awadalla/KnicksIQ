# Confirmed release implementation, October 1

The offline baseline/register, canonical review/coverage and ten-message game
reference fix are implemented on `codex/release-implementation-20261001`, based
on candidate `bf4439bbcd69e328c1d65c52e9a73dcbe4942cbe`. The owner's subsequent
[context decision](confirmed-context-decision.json) corrects the earlier claim
that an unspecified game demonstrated an identity-relevance incompatibility.
Complete tied-game narratives and canonical Boston scoring runs are also implemented.
Gold remains unfrozen. Bounded retrieval discovery is implemented. Guarded paid orchestration,
release evaluation, load, recovery, rollback and launch remain open.

The implementation worktree is
`/Users/mohamedawadalla/.codex/worktrees/release-implementation/KnicksIQ`.
The original project and candidate worktree retain their user-owned changes.
The sealed September 30 package was read and verified without modification.

`tools/release/implementation_audit.py` verifies all 485 package checksums and
93 record references, recomputes the retained canonical facts for every original
question, and applies the nine confirmed owner decisions to a fresh review.
It preserves original question/context bytes, all 120 cases, all 50 semantic
members, and all seven previously settled target sets. In particular,
`aliases_typos-006` retains its nine Atlanta game targets.

The revised review contains 61 answers, 50 clarifications and nine refusals.
This is a canonical review, not an observed runtime result or approved gold.
The three changed dispositions are:

- `single_game_narrative-006`: describe all six games tied at a one-point final
  margin: `0022500372`, `0022501016`, `0042500122`, `0042500123`, `0042500402`
  and `0042500404`. The review supplies per-game final and period scoring facts.
- `single_game_narrative-020` and `turning_points-006`: describe both maximum
  unanswered Boston runs in the December 2 loss, without causal assertions.
  Both runs were 12–0: Q2 10:07–08:25 (events 128–146) and Q3 02:29–00:03
  (events 282–299). Each scoring event retains its canonical identity, clock,
  source row and SHA256, alongside before/after scores. Any Knicks point ends
  the run; quarter breaks and zero-point events do not.

The five approved measure clarifications and eleven game-anchor requirements
are recorded per case. Follow-ups retain their immutable original contexts;
the assistant's unverified narrative is not treated as committed evidence.

“How did JB play in that game?” now resolves a unique canonical game identified
in the preceding ten messages. Missing, ambiguous, expired or unavailable game
references return “Which game?” before model admission. A newer invalid target
cannot fall back to an older game; stale committed scope cannot replace a
missing in-window anchor. Context identifies the game, while statistics come
from active-release rows. An assistant's unsupported score does not become a
fact. Verified-statistic explanations keep their existing behavior.

Deterministic identity resolution uses the complete ten validated messages,
including identities beyond an older message's model excerpt. The model still
receives the existing 2,000-byte bounded history. Session replay binds the full
in-window transcript, so a changed game outside that excerpt produces a conflict.
The query parser also distinguishes the verb “play in that game” from the NBA
play-in phase.

The identity investigation found Jalen Brunson's canonical player row, NBA ID
`1628973`, and the curated `JB` alias. The 19,016-document retained corpus has
no `JB` mention or standalone player-identity document. This inventory leaves
identity relevance unadjudicated; it does not establish incompatibility.
`aliases_typos-003` has empty immutable context and should clarify. Its proposed
identity source still needs independent relevance and current receipt mapping
before it can become evaluation gold. Its targets remain empty pending that
work. The historical `identity-incompatibility.json` output name is retained for
compatibility; its contents explicitly report no demonstrated incompatibility.

All 50 coverage entries distinguish settled targets, candidate support and
missing runtime/relevance proof. The previous 94.333% bound is conditional on
one-source documents and the broad matching-game proposal. The scorer can union
nine actual canonical sources from one genuinely complete aggregate receipt;
the current corpus contains no such aggregate. No ranked retrieval receipt or
new source mapping was manufactured.

Paid admission separately remains blocked. The stopped original smoke still
accounts for five attempted requests and $0.0322179 spent or reserved, including
$0.03205728 of unknown cancellation cost. Its journal was not reset or reopened.
September's unavailable ledger does not certify October headroom. The owner
subsequently instructed [not to worry about testing spending](confirmed-spending-direction.json),
so the historical testing dollar caps no longer block necessary validation.
The primary 720-request ceiling, actual-selection-dependent shadow request
ceiling, original load/recovery workloads, accurate cumulative accounting and
unknown reservations remain requirements. Production budget configuration is
unchanged. No paid or remote request,
new reservation, production mutation, freeze or approval occurred.

The [audit failure modes](failure-modes.md), CLI E2E specification and
[context failure modes](context-reference-failure-modes.md) were written before
their implementations. Retained red HTTP runs reproduced missing-context,
ignored-anchor, play-in parsing and long-message replay failures. HTTP checks
exercise the actual ASGI route, SQL and dedicated local Redis. They retain
requests, responses, tool captures, exact replays, conflicts, provider-attempt
counts and unchanged budget receipts before assertions. No new unit tests were
written. Verification passed 577 app/package checks, 19 report-audit checks,
26 targeted HTTP cases, repository Ruff checks and scoped Pyright. The
network-denied CLI reproduced identical bytes in two fresh directories and
retained its negative controls. Results are bound in the retained artifacts.
These checks do not replace
the original six blocked readiness checks or model-quality gates.

Private, ignored evidence is retained under
`release-artifacts/implementation-20261001/`. The authoritative new audit outputs
are `e2e-verified-final/first/implementation-register.json`, `expectation-review.json`,
`semantic-coverage.json`, `identity-incompatibility.json` and `SHA256SUMS`.
`e2e-verified-final/e2e-result.json` binds every CLI check and output.
`verification.json` records source hashes, final HTTP/API counts and commands;
`SHA256SUMS` binds retained evidence. Earlier failed and successful runs remain
in separate directories and retain their historical source scope.

To repeat the complete network-denied CLI E2E verification from this worktree,
choose a new output path; an existing path is deliberately rejected:

```sh
python3 tools/release/verify_implementation_audit.py \
  --evidence-root /Users/mohamedawadalla/Projects/KnicksIQ \
  --handoff /private/tmp/knicksiq-release-implementation-handoff.md \
  --output /private/tmp/knicksiq-implementation-recheck-NEW
```

From the generated `first` directory, `shasum -a256 -c SHA256SUMS` independently
verifies the four review outputs. The command is pinned to the exact confirmed
handoff, approved bundle, questions and retained baseline record. It has no
credential, provider, database, approval, freeze or deployment path.

Complete independent source adjudication and current receipt mappings for all
remaining target sets, then obtain content-bound gold approval before release
evaluations. Missing game context is an expected clarification, and earns no
retrieval credit on its own. The handoff's confirmed product decisions stand. Paid
execution additionally requires the original request inventory and exact
cancellation attribution, a fresh ledger, isolated runtime dependencies and
enforced current price/route/tokenizer bounds. Production launch requires
passing readiness and separate owner approval bound to the final record digest,
targets and rollback.

To repeat the HTTP checks with safe local dependencies and fresh retained receipts:

```sh
context_artifacts=$(mktemp -d /private/tmp/knicksiq-context-check.XXXXXX)
PYTHONPATH=apps/api:packages/basketball-core/src:apps/worker:apps/mcp \
TEST_MODE=true AI_PROVIDER=mock AI_API_KEY= OPENROUTER_API_KEY= REDIS_URL= \
KNICKSIQ_POSTGRES_TEST=0 RAG_QDRANT_ENABLED=false \
RAG_QDRANT_CLOUD_INFERENCE=false RAG_LLM_PLANNER_ENABLED=false \
KNICKSIQ_CONTEXT_ARTIFACT_DIR="$context_artifacts/receipts" \
/Users/mohamedawadalla/Projects/KnicksIQ/.venv/bin/python -m pytest \
  apps/api/app/tests/test_game_reference_http.py -q -o junit_family=legacy \
  --junitxml="$context_artifacts/results.xml"
```

These tests launch disposable Redis on localhost and use fixture SQL. They do
not access production sessions or budget state. The normal release path requires
the evidence loop enabled; the legacy loop-disabled deployment remains outside
this new HTTP proof.

The narrative phase has fresh proof in `narrative-regression-final/` and
`narrative-audit-e2e/`. All 602 existing and new checks pass. The six new HTTP
checks retain 16 receipts covering the original approved archive, both maximum
Boston runs, quarter boundaries and Knicks free throws, invalid score
corrections, tied extremes, foreign and non-final game exclusion, 100 tied
games beyond the model text limit, and complete versus incomplete model prose.
The two model-review checks use an explicit synthetic adapter; they do not
establish paid provider quality. Four older HTTP assertions were updated from
generic wording to the approved clarification inputs.

Canonical narrative evidence includes every represented game/period row and,
for Boston runs, the complete ordered event table used to establish the maxima.
It has no representative game ID. All stories remain in deterministic delivery
if the complete narrative exceeds the model format. A model response must name
every selected game and both endpoints of every tied run before evidence review
can accept it. Final scores and period totals do not justify causal stories.

These source changes invalidate affected older runtime proofs. The historical
root manifest remains unchanged; `narrative-verification.json` and the separate
`NARRATIVE-SHA256SUMS` bind this phase's retained evidence. The new authoritative
audit register is `narrative-audit-e2e/first/implementation-register.json`.

To repeat the narrative HTTP checks, use the same safe environment as above,
set `KNICKSIQ_NARRATIVE_ARTIFACT_DIR` to a fresh receipt directory, and run
`apps/api/app/tests/test_canonical_narrative_http.py`. No unit tests were added.

Bounded canonical discovery now runs before clarification and model admission in
an evidence-loop turn. It searches local release-scoped SQL only, at most twenty
candidate records, and captures the actual top five in order. Canonical names
resolved from ordinary player aliases and opponent IDs can expand the bounded
query. For an unidentified conversation reference, team names in the preceding
ten messages can be search terms; they do not establish a game or verify an
assistant's narrative. Retrieval cannot remove approved clarification or supply
a missing game. No evaluation ID, gold target, provider, dense embedding or paid
reservation participates in this preflight.

A two-second local discovery timeout/failure produces an explicit failed capture
and degradation; it prevents model dispatch. Cancellation cleanup is shielded
for at most one second and releases only the request's owned conversation lease.
It does not release, reset or reopen any paid accounting reservation. The new
HTTP cancellation check first reproduced a retained lease and a rejected exact
retry, then verified lease removal and successful retry/replay after the fix.

The [discovery failure modes](canonical-discovery-failure-modes.md) and seven HTTP
checks cover the original 120-question probe, primary and sampled-shadow
clarifications, canonical alias/context search terms, SQL failure, cancellation,
replay/conflict behavior and zero paid/dense/reservation attempts. These are
engineering checks against fixture SQL and disposable Redis, not admitted
primary/services-disabled/shadow release evaluations. Their original question
and context bytes remain unchanged. Capture presence and nonempty results alone
do not establish source relevance or retrieval recall. Approved gold, complete
aggregates, independent source manifests and the isolated release environment
remain requirements.

Private discovery proof is retained in `discovery-complete/`,
`discovery-regression/` and `discovery-audit-e2e/`; failed runs remain retained.
`discovery-verification.json` and `DISCOVERY-SHA256SUMS` bind this phase without
rewriting prior manifests. The authoritative current offline register is
`discovery-audit-e2e/first/implementation-register.json`. Repeat the discovery
HTTP checks in a fresh output directory with the same safe environment above,
set `KNICKSIQ_DISCOVERY_ARTIFACT_DIR`, and run
`apps/api/app/tests/test_canonical_discovery_http.py`. No new unit tests were added.

The owner [retained the current staging plans](confirmed-staging-plan-decision.json).
Both proposed Render forms were cancelled: the API remains Free, and no new
Redis service or recurring charge was added. This decision does not establish
the missing isolated dependency or capacity evidence.

The approved bundle loader now synchronizes player names, teams, positions and
jersey numbers by NBA player ID when activating a release, including an already
loaded active release. Staging preserves existing metadata. NBA IDs, SQL row
identities and stat foreign keys stay stable. The prior loader retained incorrect
seed names for 17 archive players, creating false Towns and Bridges ambiguities.
The [roster failure modes](canonical-roster-failure-modes.md) and retained red HTTP
run precede the fix. The HTTP check records all canonical roster fields and six
questions through two activations, repairs deliberately stale metadata on the
second activation, and verifies exact replay without constructing a provider.
The existing surname policy prefers a unique Knicks player; it resolves Bridges
to Mikal without changing that policy.

Roster proof establishes identity consistency, not correctness of every returned
statistic. The retained responses separately expose generic scoring averages
for rebounding, double-double and before/after All-Star questions; those require
further implementation and fresh quality proof. The authoritative current audit
is `roster-audit-e2e/first/implementation-register.json`, which binds the loader
source and both latest owner directions. No release gold or launch is approved.
