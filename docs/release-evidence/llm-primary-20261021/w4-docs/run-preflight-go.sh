#!/bin/sh
# Repeat the in-process llm_primary preflight against the OpenCode Go configuration.
#
# Prerequisites: . /tmp/go.env (provider, models, protocols, prices, allowlist, AI_API_KEY),
# the local restored release in Postgres, and Redis. Flush the workstream database once and seed
# the monthly ledger before the first run:
#   docker exec kiq-integrate-redis-1 redis-cli -n 5 flushdb
#   docker exec kiq-integrate-redis-1 redis-cli -n 5 set ai-budget:2026-10 0.07 NX
# The values below are the production placeholders ReleaseOps used; the Sentry DSN and the IP
# hash secret are format-valid stand-ins, not production secrets.
set -eu
. /tmp/go.env

export REDIS_URL=redis://localhost:56500/5
export ENVIRONMENT=production
export REQUIRE_ACTIVE_RELEASE=true
export ANALYSIS_SHADOW_SAMPLE_RATE=0.1
export CORS_ORIGINS='["https://www.knicksiq.win"]'
export PUBLIC_WEB_ORIGIN=https://www.knicksiq.win
export TRUSTED_HOSTS='["api.knicksiq.win","127.0.0.1","localhost"]'
export SENTRY_DSN='https://0123456789abcdef0123456789abcdef@o0.ingest.sentry.io/1'
export IP_HASH_SECRET='w4-docs-preflight-9f2c4e6a1b8d3f5c7e0a2b4d'
export AI_REQUEST_TIMEOUT_SECONDS=20
export PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE=1000
export PUBLIC_CHAT_RATE_LIMIT_PER_DAY=100000
export QDRANT_URL=
export QDRANT_API_KEY=
unset OPENROUTER_API_KEY 2>/dev/null || true

exec uv run --package knicksiq-api python tools/release/preflight_llm_primary.py \
  --json-out docs/release-evidence/llm-primary-20261021/ops/preflight-go.json "$@"
