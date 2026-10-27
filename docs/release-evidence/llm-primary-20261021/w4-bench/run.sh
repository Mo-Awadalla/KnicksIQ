#!/usr/bin/env bash
# Rerun the 70-question live benchmark on the production Go config: 2 trials, 140 questions.
# Artifacts are written in place (trialN.json, trialN.scored.jsonl, trialN.responses.jsonl,
# calls.jsonl, ledger.jsonl, metrics.json).
set -euo pipefail
cd "$(dirname "$0")"
. /tmp/go.env
export REDIS_URL=redis://localhost:56500/2
docker exec kiq-integrate-redis-1 redis-cli -n 2 flushdb
uv run --package knicksiq-api python bench_runner.py \
  --trials 2 --per-category 10 --out-dir .
