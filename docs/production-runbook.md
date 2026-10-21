# KnicksIQ production runbook

Production serves one immutable 2025-26 archive release. The API never migrates, seeds, ingests, generates reports, or mutates basketball data at startup. Qdrant, Redis, and OpenRouter are required for the LLM-primary path but remain optional for availability; Postgres and one validated active release are the only dependencies required for deterministic answers.

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
- OpenRouter or budget exhaustion: deterministic phrasing remains available. Do not raise the configured application cutoff (currently $2 in `render.yaml`) without owner approval.
- Sentry: application availability is unaffected. Use Render logs and synthetic checks until restored.

### Analyst reports “Model or budget unavailable”

A healthy Redis connection is not sufficient: model calls require the current
`ai-budget:YYYY-MM` ledger. The free Redis instance has no persistence, and a lost
ledger or a new month blocks reservations until an administrator reconciles it.
Do not restore a missing ledger to zero automatically.

Check provider billing, the current ledger and its `:reservations` hash. Preserve
existing charges and outstanding or uncertain calls. Restore only a missing key
with `SET NX`, without an expiry, using a conservative reconciled total below the
existing cutoff. Verify with a new turn ID: committed sessions replay their
original response, including a fallback, by design. Check `llm_validated`, not
just HTTP 200 or `state_committed`.

On 2026-09-22 the production ledger was absent while Redis sessions worked.
Provider monthly usage was $0, lifetime usage was $0.00084725, and the reservation
hash was empty. The missing ledger was restored at $0.07, covering lifetime usage
plus a conservative six-call allowance. The cutoff in force at that time was $8;
the current blueprint sets $2. Subsequent model validation/time-limit failures are
separate from this repaired budget block.

## Elevated errors

Correlate the public `request_id` with scrubbed API logs. Do not request or copy user prompts. Check Postgres pool saturation and statement timeouts first, then optional dependency timeouts. Roll back when the error rate exceeds 1% and the cause is release-specific.

## Answer-mode rollout

The authoritative launch configuration is
[the release checklist](release-checklist.md#intended-launch-configuration).

1. Deploy the pre-promotion verification build with `ANALYSIS_ANSWER_MODE=shadow` and
   `ANALYSIS_SHADOW_SAMPLE_RATE=0.1`.
2. Verify shadow validation, retrieval, cost, and latency gates without
   inspecting or retaining prompt/evidence content.
3. Set `ANALYSIS_ANSWER_MODE=llm_primary` only after the gates pass and the owner
   approves the launch configuration.
4. Roll back instantly with the drill below; no data or index rollback is required.

### Analyst runtime defaults

- `ANALYST_REASONING_EFFORT=none` and `AI_REASONING_EFFORT=none`. Do not unset either value; the
  provider otherwise reasons at high effort and truncates JSON.
- `ANALYST_PREFETCH_ENABLED=true`. Prefetch runs one tool before the first model call for a clear
  question and counts toward the loop bounds.
- Review cap 3,000 output tokens, answer cap 1,600, planning action 600 tokens. The analyst input
  budget is `see config` (`ANALYST_INPUT_TOKENS`).
- The reviewer number gate is mandatory. Do not disable it to clear latency.
- Season-level records default to the regular season and the answer states the phase. The overall
  record appears only when asked.
- Typed pre-model refusals cover instruction override, wagering and out-of-archive dates. Other
  unsupported wording reaches the analyst, which declines or explains coverage.

## Capacity, cost and latency

At the $2 cutoff, the 16,000-byte measurement supports about 1,009 questions per month on the
70-question mix and about 750 on the held-out rate. Mean cost is $0.001981 per question on the
70-question mix and $0.002668 at the held-out rate. Capacity is route dependent because OpenRouter
routing is unpinned and the adapter does not pin a provider today. See the
[final measurement](release-evidence/llm-primary-20261021/final/README.md).

Billed provider failures settle at the provider's reported cost. A call with no HTTP response
keeps the flat reservation. Every measured run reconciles the ledger delta to settled cost plus
the open reservation delta. Check the ledger and provider usage separately after an incident.

Measured latency on 140 questions (70 questions in two trials) at the 16,000-byte input budget is
p50 3,312 ms and p95 7,640 ms, with 2.74 provider calls per question. The release gate is p95 below
four seconds and is not met. Treat a p95 rise above the recorded baseline as a regression. Evidence
is in the [final measurement](release-evidence/llm-primary-20261021/final/README.md).

## Rollback drill: llm_primary to deterministic or shadow

Rehearse on a non-production service first. Production execution requires owner approval and two
operators: one changes Render, one verifies from outside. This repository run documents the drill;
it did not execute it against a deployment.

Before changing anything, record the live API deployment ID and commit, `/health/ready`
`data_version`, the current `ai-budget:YYYY-MM` total, and the Render service ID
`srv-d9cgko8js32c73bbvu10`.

### Deterministic: model-free kill switch

1. Render Dashboard, `knicksiq-api`, Environment. Set `ANALYSIS_ANSWER_MODE` to `deterministic`
   and choose **Save and deploy**. This restarts the existing image with the new value and does
   not rebuild; **Save only** does not take effect.
2. Wait for the deployment status `live`. Confirm its commit ID is unchanged and
   `GET https://api.knicksiq.win/health/ready` returns 200 with the same `data_version`.
3. From a machine outside Render, send three requests with distinct fresh `turn_id` values of at
   least 16 characters. Reusing a turn ID replays the committed response by design.

   ```sh
   curl -sS https://api.knicksiq.win/analysis/query \
     -H 'Content-Type: application/json' \
     -d '{"question":"What was the Knicks record this season?","season":"2025-26",
          "turn_id":"rollback-'"$(uuidgen | tr -d -)"'","expected_revision":0}'
   ```

   Expect HTTP 200, `"llm_validated": false`, `"degraded": true`, non-empty `citations`,
   `warnings` containing `Model or budget unavailable.`, `"refused": false`, and 53 wins and 29
   losses with `regular season` stated in the answer. Re-send the same question with `overall`
   added and expect 69 wins and 32 losses. A 200 alone is not proof; check these fields. If the
   phase or either record differs, stop.
4. Confirm model spend stopped: the OpenRouter usage counter stays flat and the ledger total is
   unchanged after the three requests. This check is operator-side, not public.
5. If any assertion fails, do not continue. Restore `ANALYSIS_ANSWER_MODE=llm_primary` with
   **Save and deploy**, re-verify, and alert the owner.

### Shadow: delivery stays deterministic, the loop is sampled

1. Set `ANALYSIS_ANSWER_MODE=shadow` and temporarily `ANALYSIS_SHADOW_SAMPLE_RATE=1.0`.
   Choose **Save and deploy**. Rate 1.0 makes the shadow path observable in a few requests;
   at 0.1 three requests can all miss the sample (0.9^3 = 0.729).
2. Wait for `live` and re-check `/health/ready`.
3. Send three requests with distinct fresh turn IDs. Expect HTTP 200 and
   `"llm_validated": false` on delivery. At least one response should carry the warning
   `Shadow verification; deterministic delivery.` when the model answer validated. If all three
   fail validation, the response carries a different warning; use Sentry event
   `analyst_shadow_verification` (`sampled=true`) to confirm the sampled path ran.
4. Restore `ANALYSIS_SHADOW_SAMPLE_RATE=0.1` with **Save and deploy** and send one more request.
   Do not leave 1.0 in production: every request then spends model budget.
5. If shadow must be the steady state, keep 0.1. Unsampled requests make no model call.

### Blueprint drift and verification limits

`render.yaml` declares a literal `value: llm_primary` for `ANALYSIS_ANSWER_MODE`. A later
Blueprint sync from a push that changes that file overwrites the Dashboard value. Dashboard
**Save and deploy** is the emergency path; make the durable value change in `render.yaml` only
through the normal reviewed release. Until then a Blueprint sync can revert the rollback.

`llm_validated=false` alone does not distinguish deterministic from shadow. The warning text and
provider spend do. Production responses omit `route` and `tool_calls`, so verify with
`llm_validated`, `degraded`, `warnings`, `citations`, and `data_version`. Public rate limits
(default 10 per minute and 100 per day per client) cap how many probes one address can send.
Render's environment variable save options are documented at
https://render.com/docs/configure-environment-variables.

## Secret rotation

Rotate one secret at a time: database, Redis, Qdrant, OpenRouter, Sentry, Formspree, then the IP-HMAC secret. The HMAC secret intentionally invalidates rate/cache keys. Redeploy the same immutable image, run smoke checks, and revoke the old secret.

## Backups and monitoring

Neon Free does not replace an application-owned backup. Retain the validated,
hash-bound release bundle as the source of truth and rehearse rebuilding a new
Neon project from it. Sentry must have API/frontend exception alerts, latency
tracing, and an external `/health/live` uptime check. Session replay stays
disabled and `before_send` removes requests, headers, cookies, users, prompts,
and breadcrumbs.
