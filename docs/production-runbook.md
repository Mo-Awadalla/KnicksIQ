# KnicksIQ production runbook

Production serves one immutable 2025–26 archive release. The API never migrates, seeds, ingests, generates reports, or mutates basketball data at startup. Qdrant, Redis, and OpenRouter are required for the LLM-primary path but remain optional for availability; Postgres and one validated active release are the only dependencies required for deterministic answers.

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
- Redis: AI synthesis and shared caching are disabled during the outage. In-process limits protect one instance and deterministic facts remain available. A restarted free Key Value instance loses only reconstructible rate-limit, cache, and AI budget state.
- OpenRouter or budget exhaustion: deterministic phrasing remains available. Do not raise the $8 application cutoff without owner approval; the provider guardrail is $9.
- Sentry: application availability is unaffected. Use Render logs and synthetic checks until restored.

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
