# Confirmed release implementation, October 1

The offline baseline/register, canonical review/coverage and ten-message game
reference fix are implemented on `codex/release-implementation-20261001`, based
on candidate `bf4439bbcd69e328c1d65c52e9a73dcbe4942cbe`. The owner's subsequent
[context decision](confirmed-context-decision.json) corrects the earlier claim
that an unspecified game demonstrated an identity-relevance incompatibility.
Gold remains unfrozen. Bounded retrieval discovery, guarded paid orchestration,
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
September's unavailable ledger does not certify October headroom. Primary stays
at 720 requests/$0.50; shadow retains its actual-selection-dependent request cap
and $0.50 limit; combined/monthly limits stay $1.10/$2. Original load/recovery
reservations are still required before evaluation. No paid or remote request,
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
