# KnicksIQ architecture

## Production system

KnicksIQ serves one immutable Knicks 2025-26 archive. Render hosts a static
React application and a free, read-only FastAPI service. Neon Free Postgres is
the authoritative store. Render Free Key Value supplies ephemeral shared rate
limits, answer caching, session state, and AI budget state. Qdrant Cloud holds
release-versioned retrieval indexes. Sentry receives scrubbed errors and
low-sample traces.

Models run on OpenCode Go, the owner's subscription, at
`https://opencode.ai/inference/go/openai/v1`. `deepseek-v4.1-flash` writes over
Chat Completions and `gpt-6-luna` reviews over the Responses API, so the
reviewer is a different model family from the writer. `AI_MODEL_PROTOCOLS` maps
a model to its wire protocol; a model it does not name uses Chat Completions.
Go reports no per-call cost, so `AI_MODEL_PRICES` (USD per million input/output
tokens) prices each call and the monthly ledger settles real usage. Each analyst
turn sends a random session id in `x-opencode-session`, never the user's session
token, plus the configured `User-Agent`. The writer and reviewer compose
validated answers from backend-computed claims or select bounded retrieval; they
never author a number.

OpenCode's terms say the service is for "your own internal use, and not on
behalf of or for the benefit of any third party", and Go is described as being
for coding-agent traffic. A public site serves third parties. The owner accepted
that risk for a small hobby project. If the account is suspended, every answer
falls back to the deterministic path. The full record, including the probe
results and the exact switch back to OpenRouter, is in
[the OpenCode Go decision](release-evidence/llm-primary-20261021/opencode-go/README.md).

Postgres and one validated active `dataset_releases` row are required.
Qdrant, Redis, and the model host are optional at request time. Their failure
must not prevent deterministic factual answers.

## Immutable release boundary

NBA access, normalization, reconciliation, report generation, and manual report
review happen offline. The release tools export a versioned bundle containing
games, events, period scores, team and player box scores, teams, players, and
one hash-bound reviewed report per game. The loader verifies the supplied
SHA-256, validates the bundle, and imports it transactionally and idempotently.

All public basketball queries are scoped to the active validated release. The
API does not run migrations or mutate archive data at startup. Because Render's
Free tier does not support pre-deploy commands, the release operator runs the
expand-only Alembic migration against Neon before deployment.

## Runtime request flow

The web application calls the public API anonymously. Archive endpoints read
the active release directly from Postgres. `POST /analysis/query` applies the
typed pre-model refusal table first. It refuses only instruction override,
wagering and out-of-archive date text, before any provider call. Ambiguous live,
injury, trade and prediction wording reaches the analyst, which answers the
archive part, declines or explains coverage.

When `ANALYST_EVIDENCE_LOOP_ENABLED=true`, the request runs one bounded evidence
loop:

1. Load the active release and resolve the question scope. Season-level records
   and stats retain all phases unless explicitly or contextually restricted.
2. Optionally run deterministic prefetch for a clear question: `discover_facts`,
   `get_team_stats` or `get_player_stats`. `ANALYST_PREFETCH_ENABLED` defaults to
   true.
3. Let the model choose from eleven registered tools. The backend computes every
   number, emits an immutable `VerifiedClaim` with receipts and applies the
   resolved scope. The model can reference claim IDs, never overwrite values.
4. Run the reviewer with prompt `analyst-balanced-v6` and validator
   `whole-answer-v3`. A deterministic gate requires every answer number to match
   a claim, receipt or capability value. The model returns one verdict per
   backend-owned sentence span. One revision and re-review are allowed.
5. Deliver the validated answer with `llm_validated=true`. Any provider, budget,
   validation or deadline failure falls back to cited deterministic facts with
   `degraded=true` and `llm_validated=false`.

The tools cover player and team statistics, player threshold games, window
comparisons, fact discovery, archive search, evidence expansion, canonical game
narratives, game flow, team splits and period scoring.
Period and play-by-play questions are in scope. The fallback and the team tools
apply the same resolved population, including explicit and inherited phase restrictions.

When an opponent appears in an ambiguous single-game question, the API applies
explicit win, loss, closest, and biggest-win conditions to final scores and
lead-change conditions to play-by-play before asking which game was meant. A
lost lead requires the opponent to take the lead after NYK led. A comeback
requires NYK to lead after trailing, while an erased deficit can include a
later tie. A lost lead can still end in a Knicks win. One fit proceeds, several
list only matches, and zero matches are reported without inventing a game.
Missing, nonmonotonic, or unreconciled scoreboards trigger an unverified-data
clarification instead of being counted as a match or a zero-match result.
For a uniquely selected lead-change game, its narrative claim includes the final
score and the first verified transition pair for each requested condition, keeping
the evidence complete without overwhelming the writer/reviewer source budget.
These strict-lead and tie-inclusive deficit-erasure definitions are implementation
drafts pending owner review.

With the evidence loop disabled, deterministic requests naming one opponent
resolve lead-change conditions before generic archive retrieval. A single
verified fit returns its canonical narrative claim and citations without
inferring a cause beyond the observed score transitions.

The deterministic modes remain. `deterministic` bypasses planning and synthesis.
`shadow` returns the deterministic response and validates a sampled candidate in
the same metered loop; the non-evidence path schedules its sampled candidate in
the background. `llm_primary` returns the validated model answer. Any
vector, model, Redis budget, timeout, parsing, validation or deadline failure
returns cited deterministic facts with `degraded=true` and `llm_validated=false`.
A validated refusal sets `refused=true` with `llm_validated=true` and
`degraded=false`; the flag is not an error signal.

Production routing deliberately excludes ingestion, job enqueue, run
detection, report creation/deletion, Swagger, and OpenAPI. Workers and MCP are
offline/development packages, not deployed production services.

## Data model

`dataset_releases` owns activation and validation metadata. Basketball rows are
release-scoped through `release_id`; a game identity is unique inside a release.
The core hierarchy is:

```text
dataset_releases
  games
    game_events
    period_scores
    team_game_stats
    player_game_stats
    scoring_runs
    bad_stretches
    reports
```

Teams and players supply entity metadata. Documents/chunks support local and
legacy retrieval paths. Jobs exist for offline/development workflows only.
See `docs/data-model.md` for field-level detail.

## RAG indexing

The offline indexer can create immutable Qdrant collections for game summaries,
box-score facts, reviewed reports, and possession chunks. It validates counts
before atomically promoting stable aliases. Production uses Qdrant Cloud
Inference with the configured 384-dimensional MiniLM model; the API image
contains no PyTorch or local model weights. Postgres remains the authoritative
source and can rebuild every collection.

## Safety and operations

- Readiness requires Postgres and a validated active release; optional
  dependencies are reported but do not fail readiness.
- Anonymous clients are protected by per-minute and per-day limits using a
  daily HMAC of the resolved client address.
- API responses include request IDs and hardened security headers.
- Sentry scrubbing removes request data, headers, cookies, environment, user
  data, prompt text, and breadcrumb details; replay is disabled.
- Migrations are expand-only so the previous image and release remain available
  for rollback.

Operational procedures and launch gates live in
`docs/production-runbook.md` and `docs/release-checklist.md`.
