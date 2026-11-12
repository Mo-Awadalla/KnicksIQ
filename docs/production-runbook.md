# KnicksIQ production runbook

Production serves one immutable 2025–26 archive release. The API never migrates, seeds, ingests, generates reports, or mutates basketball data at startup. Qdrant, Redis, and OpenRouter are required for the LLM-primary path but remain optional for availability; Postgres and one validated active release are the only dependencies required for deterministic answers.

## Liveness, readiness, and the container probe

`GET /health/live` is process liveness only. It touches no dependency, and Render uses
it as the deploy health check so a first deploy can complete before release data is
loaded. `GET /health/ready` is the go-live gate: it checks Postgres, one validated
active release, and the production configuration sanity checks, reports optional
Qdrant/Redis/OpenRouter state separately, and returns 503 while any required check
fails. A passing liveness probe never means the service is serving the approved data.

```bash
curl -sS -H 'X-Forwarded-Proto: https' "$API/health/live"
curl -sS -H 'X-Forwarded-Proto: https' "$API/health/ready"
```

Production redirects plaintext HTTP to HTTPS, and that redirect stays in force. The
container `HEALTHCHECK` runs inside the container against its own loopback port, where
no TLS terminator exists, so it presents the same scheme header a trusted edge sends
and requires HTTP 200 from `/health/live`:

```bash
docker exec knicksiq-api python -m app.api.health_probe
```

A redirect, a timeout, or any other status exits non-zero and the container is marked
unhealthy. The probe never disables the redirect and never sends a public caller's
header. It trusts the scheme header only because it connects from loopback, so if
`FORWARDED_ALLOW_IPS` is narrowed to the edge address, loopback must remain in that
list or the probe will be redirected and the container will report unhealthy.

## Verification requirements

These are controls that must be confirmed in the deployed environment. They are
requirements, not claims about the current deployment.

1. **Independent provider cap.** The application reserves against a shared Redis
   ledger using `OPENROUTER_MONTHLY_CUTOFF_USD=2`. A missing ledger restarts at zero.
   Confirm a provider-side limit bounds total charges to the owner's approved
   amount. Record the value and its verification date. Do not infer it from
   application logs or raise either limit automatically.
2. **Proxy trust.** The container must receive traffic only through the Render edge.
   Confirm the edge's `X-Forwarded-Proto` is honored (otherwise every public request
   is redirected) and that `request.client.host` is the end-user address (otherwise all
   users share one rate-limit identity). Both depend on uvicorn's trusted
   forwarded-for addresses (`FORWARDED_ALLOW_IPS`, default loopback). Verify by
   comparing observed per-client limiting in production with the edge's forwarding
   configuration.
3. **Runtime database grants.** The API never writes basketball data or schema. Confirm
   the runtime role holds only `SELECT` on the application tables and views and cannot
   run DDL, then record the observed grants. Do not assume least privilege from the
   connection string alone.
4. **Container health contract.** Confirm the deployed container reports `healthy` and
   that the probe succeeds from inside the container using the command above, not only
   through the public edge.
5. **Rate-limit storage bound.** The in-process limiter tracks at most 10,000 client
   identities. Timestamps older than the minute or day window are trimmed on amortized
   sweeps, and a client's state is dropped once both windows are empty, so an abandoned
   day-rotating HMAC identity is pruned instead of accumulating. Live windows are never
   evicted. When the table is full, a request from an untracked identity is refused with
   the public `429` and allocates nothing, while an identity that is already tracked
   keeps the minute and day debt it has accrued. Redis remains the authoritative shared
   limiter when it is configured. Confirm the process' resident memory stays flat under
   sustained distinct-source traffic, and that a source refused at the cap stays refused
   instead of being admitted after another client's window is dropped.

## Repeatable local production scenario

`tools/release/production_e2e.py` starts an isolated Postgres, Redis, production-profile
API, and built frontend on fresh ports `19430`–`19433` and writes its evidence to
`release-artifacts/production-completion/`. It uses no provider traffic.

```bash
uv run --frozen --all-packages python tools/release/production_e2e.py
```

## Bounded analyst evaluation

`tools/release/eval_runner.py` evaluates the current worktree against an isolated local
restore. The disabled profile records all 120 cases without provider traffic. The proposed
label-enrichment tool adds identity metadata only; it does not freeze labels or approve
semantic targets. Keep unresolved gold blockers visible.

Service mode is separate and never reads keys from `.env`. An operator must issue a
`evaluation-budget-approval-v4` binding the evaluation identity, candidate commit and source
digest, model, upstream and spend bound, and must provide a provider-side billing limit
independently. Changed source requires a new approval. The runner
uses loopback Redis and the evaluation-only signed-proof entrypoint. Every attempt is
persisted before network IO. A local fake proves the bounded request boundary only, not
provider quality, and is blocked by the scorer.

Do not deploy or promote from local evidence. The provider-side cap, edge behavior, runtime
database grants, hosted health and directory membership remain separate production checks.

## Failed deployment and rollback

1. Stop promotion if `/health/ready` or the synthetic archive/analyst checks fail.
2. Keep the previous Render image active. Migrations are expand-only, so the previous image remains compatible.
3. If activation already occurred, mark the previous validated `dataset_releases` row active and the failed row staged. Switch Qdrant aliases back to the prior versioned collections.
4. Verify archive totals, one known game, one box score, one report, and one deterministic analyst question.

## Database restore and rebuild

1. Preserve the failed database and record the active release version and bundle SHA-256.
2. Create or reset the Neon database, run `alembic upgrade head`, then run `knicksiq-load-release <bundle> --sha256 <sha> --activate`.
3. The loader is transactional and idempotent. It must complete without NBA.com access.
4. Rebuild Qdrant from Postgres with `knicksiq-build-rag-index --season 2025-26 --data-version <version> --reset-qdrant`. Confirm Recall@5 before the alias switch.
5. Target core archive RPO is zero from the immutable bundle and RTO is under four hours.

## Dependency outage

- Qdrant: leave the API up; responses fall back to deterministic Postgres answers with `degraded=true`. Rebuild or resume the cluster, validate counts and Recall@5, then switch aliases.
- Redis: AI synthesis and shared caching are disabled during the outage. In-process limits protect one instance and deterministic facts remain available. A restarted free Key Value instance loses only reconstructible rate-limit, cache, and AI budget state; a lost monthly ledger restarts at zero (see below).
- OpenRouter or budget exhaustion: deterministic phrasing remains available. Production uses `OPENROUTER_MONTHLY_CUTOFF_USD=2` from `render.yaml`; the `8.0` code default applies only where the variable is absent, which is never a production figure. Do not raise the application cutoff without owner approval. The application cutoff is enforced in-process only, so an independent provider-side monthly limit is a separate control that must be set and confirmed by the owner (see verification requirements).

### Analyst reports “Model or budget unavailable”

Budget reservations are atomic and idempotent per reservation identity. A reservation
is charged before the call and settled to the reported cost afterwards; unknown or
timed-out calls stay charged. The ledger is `ai-budget:YYYY-MM` with the outstanding
`ai-budget:YYYY-MM:reservations` hash, and it is `PERSIST`ed on every reservation.

The recorded owner decision favors availability when the ephemeral ledger is lost.
A missing ledger starts at zero. Preserve that policy unless the owner replaces it.

The application cutoff bounds reservations only while the ledger survives.
`allkeys-lru` eviction and restarts can repeatedly reset it within one month.
`PERSIST` removes expiry but does not prevent LRU eviction.
A verified provider-side limit must independently bound total billed usage.

A turn whose model call was not attempted because the ledger was exhausted still
commits a deterministic answer. Check `llm_validated` and the response `outcome`, not
just HTTP 200 or `state_committed`, and verify with a new turn ID: committed sessions
replay their original response by design.

Historical record (policy since superseded): on 2026-09-22 the production ledger was
absent while Redis sessions worked; provider monthly usage was $0, lifetime usage was
$0.00084725, the reservation hash was empty, and the missing ledger was restored at
$0.07 against the then-current $8 cutoff. The current blueprint cutoff is $2 and a
missing ledger no longer blocks reservations.

## Elevated errors

Correlate the public `request_id` with scrubbed API logs. Do not request or copy user prompts. Check Postgres pool saturation and statement timeouts first, then optional dependency timeouts. Roll back when the error rate exceeds 1% and the cause is release-specific.

## Answer-mode rollout

1. Deploy with `ANALYSIS_ANSWER_MODE=shadow` and
   `ANALYSIS_SHADOW_SAMPLE_RATE=0.1`.
2. Verify shadow validation, retrieval, cost, and latency gates without
   inspecting or retaining prompt/evidence content.
3. Set `ANALYSIS_ANSWER_MODE=llm_primary` only after owner sign-off.
4. Roll back instantly by setting the mode to `deterministic`; no data or index
   rollback is required.

## Secret rotation

Rotate one secret at a time: database, Redis, Qdrant, OpenRouter, Sentry, Formspree, then the IP-HMAC secret. The HMAC secret intentionally invalidates rate/cache keys. Redeploy the same immutable image, run smoke checks, and revoke the old secret.

## Backups and monitoring

Neon Free does not replace an application-owned backup. Retain the validated,
hash-bound release bundle as the source of truth and rehearse rebuilding a new
Neon project from it. Sentry must have API/frontend exception alerts, latency
tracing, and an external `/health/live` uptime check. Session replay stays
disabled and `before_send` removes requests, headers, cookies, users, prompts,
and breadcrumbs.

## Verification and promotion

`search_archive` records the fused ranking it actually emitted, bound to the request id
and release, in the same `tool_calls` trace with `stage: "retrieval"`. Recovery searches
record it too. The recorded ordering is not truncated to flatter a metric, and provider
call timing is read only from the `orchestrate`, `revise` and `review` stages.

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
