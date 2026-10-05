# Confirmed release implementation, October 1

The offline baseline/register, canonical review/coverage and ten-message game
reference fix are implemented on `codex/release-implementation-20261001`, based
on candidate `bf4439bbcd69e328c1d65c52e9a73dcbe4942cbe`. The owner's subsequent
[context decision](confirmed-context-decision.json) corrects the earlier claim
that an unspecified game demonstrated an identity-relevance incompatibility.
Complete tied-game narratives and canonical Boston scoring runs are also implemented.
Gold is frozen after [content-bound owner approval](confirmed-gold-direction.json).
Bounded retrieval discovery is implemented. Dense qualification, guarded paid
orchestration, release evaluation, load, recovery, rollback and launch remain open.

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
`1628973`, and the curated `JB` alias. The original 19,016-document retained corpus has
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
that original corpus contains no such aggregate. New source-unit implementation
and actual local HTTP proof are described below. No ranked receipt or source
mapping was manufactured.

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
statistic. The retained responses separately exposed generic scoring averages
for rebounding, double-double and before/after All-Star questions. The authoritative current audit
is `roster-audit-e2e/first/implementation-register.json`, which binds the loader
source and both latest owner directions. No release gold or launch is approved.

The [requested statistic failure modes](requested-player-stats-failure-modes.md)
and six HTTP specifications preceded those statistic fixes. All six first failed
against independently computed raw-bundle values, then passed. Rebounding and
assisting wording resolves to the requested metric; explicit requested metrics
cannot be replaced by an unrelated model tool metric. Double-doubles count
observed appearances with ten or more in at least two of points, rebounds,
assists, steals and blocks. Triple-doubles qualify; DNP rows do not.

Before/after All-Star comparisons now keep both complete scoped populations,
appearance denominators, dates, source receipts and baseline claims in a single
combined claim. The 2025-26 boundary is February 15, 2026, independently verified
from [the official NBA calendar](https://www.nba.com/allstar/2026); unsupported
seasons request a supported boundary date. A requested regular-season scope
excludes postseason, while the all-phase archive includes it explicitly.

All 616 app/package/report-audit checks pass in `stats-regression/`, with fresh
HTTP receipts and unchanged original questions. `stats-red/`, `stats-complete/`,
`stats-verification.json` and `STATS-SHA256SUMS` preserve the before/after proof.
Repeat the focused checks with the safe environment above, a new
`KNICKSIQ_STATS_ARTIFACT_DIR`, and
`apps/api/app/tests/test_requested_player_stats_http.py`. These deterministic
checks do not approve gold or establish actual paid-provider or hosted readiness.

Complete opponent result and player identity units are now derived from canonical
SQL using one recipe for every opponent and player, without evaluation inputs.
For the approved archive, the offline index contains 29 opponent units and 20
player identity units. Opponent units retain every game's NBA identity, date,
phase, teams, score and result, with explicit full populations and source hashes.
They have no representative game ID. Player units distinguish canonical roster
fields from the project's curated alias policy and cannot establish a missing
game or performance fact.

The [archive-unit failure modes](archive-unit-failure-modes.md) and HTTP
specification preceded implementation. Retained red proof first had only
individual game documents. New HTTP proof retrieves the complete nine-game
Atlanta result document in the actual top five, compares every retained row and
text fact against the independent approved raw bundle, and only then resolves
its nine canonical source mappings through the unchanged mapping path.
A regular-season request excludes the broader unit. The JB identity document
is also actually ranked; the unanchored question still asks “Which game?” with
no asserted performance fact. Repeated index builds produce identical unit bytes.

Scope and content are revalidated against current SQL before a unit enters the
analyst tool result. Fusion distinguishes game-less unit identities and uses
actual term occurrences and exact requested populations. A complete opponent
population and an identity for an unanchored named player can receive ordinary
scope-match boosts; no evaluation target or case ID participates. These actual
retrieval results do not establish all 50 semantic cases' approved relevance.

`--index-revision source-units-v1` selects a new immutable physical namespace for
changed source content. It does not change aliases or reset existing collections.
Unit-aware candidates receive the four additional payload indexes in every
collection; the stored embedding identity records the unit recipe. Existing
production dense query filters remain compatible by default. Enable
`RAG_ARCHIVE_SOURCE_UNITS_ENABLED=true` only with the independently verified new
candidate index, and bind that configuration in future release evidence.

The broad unit-phase run retained 609 passes and eight failures: two legacy
index compatibility checks and six older HTTP assertions that assumed every
document had one game ID. Compatibility was restored without changing those
unit tests; the HTTP assertions now verify complete game populations or explicit
player identity scopes. All 34 focused retrieval/index/worker/discovery checks
then passed in `units-final-http/`. The original full 120-question local probe
still denies every provider, dense and reservation attempt. These are local
engineering results; PostgreSQL, hosted index enforcement, source approval,
counted provider quality and the original release workloads remain pending.

The subsequent full run passed all 617 app/package/report-audit checks in
`units-regression-final/`. After separating query-dependent ranking details
from immutable source facts, 15 focused HTTP/retrieval checks passed in
`units-stable-source-final/`, including the original 120-question probe. A
source retrieved through two different queries now has an identical evidence
body; actual scores and fusion details remain in the separate search capture.

The independent, network-denied CLI reads the pinned raw bundle and alias policy
without importing the runtime source builder. It verifies all 49 units and six
actual ranked unit receipts, reproduces identical output bytes, and rejects
re-signed wrong facts, inflated sources, aliases, extra text/fields, missing or
duplicate units. The [source-verification failure modes](archive-source-verification-failure-modes.md)
preceded the CLI specification. Retained negative controls include a red run
that exposed acceptance of unsupported identity prose in an unobserved unit.
`source-verifier-independent-final/` contains the corrected verification and
its exact repeat. Repeat with a new output directory:

```sh
python tools/release/check_archive_sources.py \
  --bundle /Users/mohamedawadalla/Projects/KnicksIQ/release-artifacts/2025-26/reliability-approved-20260928.json.gz \
  --units release-artifacts/implementation-20261001/units-stable-source-final/units/index/archive_units.jsonl \
  --observations release-artifacts/implementation-20261001/units-stable-source-final/units \
  --output /private/tmp/knicksiq-source-verification-repeat
```

This establishes source integrity and receipt consistency. Semantic relevance,
approved gold, hosted provenance and release readiness remain separate open checks.

The full local question inspection then exposed unrelated generic totals in
explicit average, threshold, percentage, starts and window requests. The
[archive statistic failure modes](requested-archive-statistics-failure-modes.md)
and HTTP specification preceded the fixes. Fourteen requests first failed and
then passed independently calculated typed values and full source populations.
Three additional defined extrema failed before their fix; all 17 now pass.
Highest/lowest scoring and worst loss by margin retain every tied game.

First and final game windows select the requested end of the archive. Player
windows select observed appearances before taking N. Total player points,
summed-makes shooting percentage and starter flags retain their true raw
fields and denominators. A unique canonical Knicks first name resolves before
fuzzy prose, correcting the Mikal question's erroneous Wells match. Existing
undefined measures and ten-message game-reference rules remain in force.
All 68 focused existing resolver, analyst, player-statistic and context checks
pass in `archive-stats-regression-final/`; the 17 requests and six existing
narrative checks pass in `archive-stats-extrema-final/`. Repeat the HTTP check
with the safe environment above, a fresh `KNICKSIQ_ARCHIVE_STATS_ARTIFACT_DIR`,
and `apps/api/app/tests/test_requested_archive_statistics_http.py`.

An additional Hart last-five-appearances check exposed misleading full-archive
window dates. Player claim windows now use the actual observed appearance dates.
All 18 requests pass alongside six existing player-statistic and seven discovery
checks in `archive-stats-final/`. The original immutable 120-question probe also
passes independently in `archive-stats-cohort-final/`; this checks trace capture
and paid-dispatch denial, not answer correctness for every original question.
The cohort exports its full source units from the same disposable database used
for the captured queries. The initial verifier input mixed approved-release
cohort captures with `analytics-test` cancellation fixtures. Verification
correctly rejected that foreign source in `archive-stats-source-verification/`;
its failure and scope diagnosis are retained. The isolated canonical cohort
verifies successfully in `archive-stats-cohort-source-verification/`, including
all 49 units and 16 actual ranked unit receipts. Candidate indexes and runtime
receipts must share their release and SQL identities.

The owner identified the project's `.env` as the credential source. Read-only
provider checks authenticated that key and observed $30 purchased and
$27.958149308 used, leaving approximately $2.04. They issued no completion or
mutation. This file's Redis points to localhost and its database is a different
resource from the isolated `.env.rc.local` database. These observations do not
certify hosted dependency readiness or authorize production state mutations.

The [current independent source review](source-relevance-review.md) now records
supported source proposals for all 50 semantic cases against actual captures.
Seven settled target sets remain unchanged; 43 new sets include canonical JB
identity and fine event/period sources for all five measure clarifications.
All 184 source units and 67 actual ranked unit receipts are independently
verified. Exact proposals remain in the private `source-support-20261003/source-units/`
evidence. The owner approved the exact 120-case expectations and 50-case targets;
the frozen contract is accepted by the actual release runner. See the
[gold approval and frozen-file digest](source-relevance-review.md#content-bound-owner-gold-approval).
Source support and gold approval do not certify retrieval recall or launch.

Publication preparation uses a separate checkout under
`/private/tmp/KnicksIQ-release-publish-20261001` because the current permission
profile makes the original implementation worktree read-only. The owner chose
to publish only the new release work; older main-checkout edits remain untouched.
The portable [synthetic archive](../../../apps/api/app/tests/fixtures/README.md)
lets CI execute the same HTTP assertions without publishing the private approved
archive. Set `KNICKSIQ_APPROVED_BUNDLE` explicitly for the original pinned-data
checks. Synthetic CI results cannot replace source approval or model-quality gates.

The counted journal now binds the exact owner spending direction when removing
historical testing dollar caps. Counts, actual shadow membership, positive price
bounds, stopped/pending journals, unknown costs and production monthly accounting
remain enforced. [Failure modes](verification-spending-failure-modes.md) and HTTP
specifications preceded the change. This is one accounting step, not completion
of guarded live orchestration or a supported resume of the original smoke.

A free temporary Upstash dependency experiment was also attempted. It returned
credentials, but five TCP checks at the application's 200 ms connection timeout,
a longer TCP control and a REST connectivity control timed out. No state was
written to it; no Render plan, provider completion or production state changed.
Its documented three-day expiry is retained. It remains unadmitted, and credentials
stay in ignored private files in the original implementation checkout.

The October 3 [measure-source audit](source-relevance-review.md#october-3-source-integrity-findings)
adds a network-denied CLI and 25 passing subprocess E2E cases. All 101 games
have complete verified period populations, establishing distinct fewest-Q3-point
and worst-Q3-margin candidates without changing clarification policy. A raw
scoring-sequence discrepancy in Milwaukee game `0022500125` is corroborated by
the official NBA page; only 100 games pass that raw sequence check. Exploratory
point reconstruction matches period and player box totals but does not approve
repaired intermediate scores. Evidence stays in the main project's ignored
`release-artifacts/source-support-20261003/`. Gold, complete indexed source
mappings, dense retrieval, guarded live orchestration and the original release
workloads remain open.

The owner subsequently selected
[independent derived-source validation](confirmed-scoring-source-direction.json).
The resulting [per-action source check](source-relevance-review.md#complete-independent-per-action-derived-source-verification)
matches every original event to primary NBA action-list order and reconciles all
101 games, 816 periods and 2,748 player box rows. It retains the raw scoreboards,
153 incorrect canonical event classifications and the running-caption discrepancy.
`tools/release/check_derived_scoring.py` exercises the independent offline CLI with
network denied, including corruption controls. This closes per-action scoring
provenance only: target definitions, indexed/ranked relevance, owner gold approval
and full release workloads remain open.

Complete [pinned measure comparisons](source-relevance-review.md#complete-pinned-comparison-evidence)
now distinguish 12 quantitative alternatives across the full 101-game archive,
82 regular-season games and 19 postseason games. All tied source boundaries
remain available. The CLI has 21 passing network-denied E2E cases; it binds the
trajectory and independent source-review digests and rejects reduced populations.
These are proposal facts, not metric defaults, ranked mappings, approved targets
or a gold freeze. The five approved measure clarifications still stand.

The [release-scoped comparison source store](source-relevance-review.md#release-scoped-comparison-source-integration)
now binds independently supplied bundle, trajectory, source-review and comparison
digests to the full canonical SQL projection without rewriting the archive.
The complete exported inventory is 184 source units, including all 101 game
scoring units and 12 explicit scope/family comparisons. An independent,
network-denied verifier exercises 22 retained CLI E2E cases. The new HTTP check
uses actual SQL, ASGI and isolated Redis, including idempotent replay, conflict,
source-corruption rejection and unchanged accounting.

Run `tools/release/import_comparison_source.py --help` for the explicit local
SQLite import/export command. Its `--initialize-empty` mode rejects an existing
store; all four input SHA-256 values are required. The independent unit verifier
also requires `--comparison-proof` and `--comparison-proof-sha256` together for
derived units. The trusted proof file binds the four input paths and digests.
Private repeatable evidence remains in `release-artifacts/source-support-20261003/source-units/`.

The existing source HTTP E2E can use the exact approved proof via
`KNICKSIQ_DISCOVERY_COMPARISON_INPUTS`; without that opt-in it uses the independent
portable two-game fixture. For the full original cohort, also set
`KNICKSIQ_APPROVED_BUNDLE` and a fresh `KNICKSIQ_DISCOVERY_ARTIFACT_DIR`, then run
`apps/api/app/tests/test_canonical_discovery_http.py::test_original_cohort_records_real_local_discovery`.
Neither fixture execution nor local pre-admission capture approves targets,
freezes gold, transmits provider requests or completes the full release gates.

## October 5 implementation and verification

The publication checkout now contains the requested calculation and evidence-loop
fixes: complete leaders, splits, monthly records, requested comparisons, quarter
scoring, player profiles and scope-exact fallback. Record questions retain both
wins and losses. Advertised team metrics and typed tool actions share one finite
vocabulary; team-only metrics cannot enter player calculations.

Complete record evidence uses the existing final-answer writer and mandatory
whole-answer review without increasing the original model, tool, input, output
or deadline limits. Both counts must fit and validate together; otherwise the
complete factual fallback is delivered. Shorter duplicate tool instructions
preserve space for compact canonical discovery. Behavioral repair checks remain;
assertions that merely pinned prompt wording were removed.

Counted execution retains every prior request, settled charge, uncertain exposure
and normal hold. The separately authorized known-cost continuation creates a new
exclusive descendant rather than resuming a stopped journal. A real Redis
settlement exposed sub-nanodollar floating-point serialization; floor comparison
now uses the existing conservative nanodollar conversion, while the raw $2 cutoff,
one-nanodollar deficit rejection and exact reservation inventory remain enforced.

Hosted CI also exposed missing static type narrowing in the private guard/load
controllers. The closure adds the existing optional-field, callable and descriptor
types without relaxing runtime checks. Gitleaks identified the historical
`DESIGNATED_KEY_SHA256` integrity digest as a credential; the existing exact
fingerprint exception list now records only that proven false positive. No
credential, scanner rule or file-wide exclusion was added.

Repeatable local evidence is retained privately under
`release-artifacts/release-execution-20261003/`:

- `backend-ci-closure-20261005/junit.xml`: final integrated backend results after
  the 755-check delivery pass and hosted type-narrowing closure.
- `known-cost-continuation-final-20261005/`: 118 passing accounting, transport,
  load-prerequisite and actual socket checks; these are not live-model quality.
- `paired-record-final-green-20261005/`: six approved-archive HTTP cases covering
  full records, omitted counts, input limits and player/team metric boundaries.
- `record-socket-ci-closure-20261005/`: actual Uvicorn/HTTP proof of 69 wins and
  32 losses across all 101 approved games, three synthetic model rounds,
  whole-answer review and exact replay, with zero real provider requests.
- `disabled-delivery-original120-20261005/`: final unchanged 120-case,
  services-disabled capture and original-scorer evidence. This cannot establish
  dense retrieval recall or primary-model quality.
- `frontend-integration/` and `delegated-browser/`: 40 passing Playwright cases,
  26 retained screenshots and 16 axe audits. The final audited UI source hashes
  remain unchanged, with no serious/critical accessibility findings.
- `qa-restart-recovery-20261004/` and
  `qa-redis-loss-recovery-20261004-accepted/`: actual owned-runtime restart and
  Redis-loss recovery. The retained chain covers 24 HTTP exchanges and 62 checks;
  neither is a coordinated deployment rollback rehearsal.

The original primary/shadow/load release gates are **not passed**. Fresh
no-completion admission observed the exact pinned `morph/fp8` endpoint at status
`-2`, not the required healthy status `0`. The verifier denied execution before
creating a goal journal or sending any completion, then was stopped. No provider
substitution, request-cap reduction, cohort reduction or budget reset was made.
See `pinned-provider-unavailable-20261005.json` for the observed public metadata.

`release-record.json` in that private evidence directory binds the final tested
source, all 17 original checks, retained evidence and explicit blockers.
Read-only hosted deployment/alias observations are not a rollback snapshot.
Production readiness, coordinated rollback, deployment and alias promotion
remain unapproved. Draft PR #6 publishes only the authorized new release work;
the original checkout, sealed September package and unrelated user edits remain
untouched.
