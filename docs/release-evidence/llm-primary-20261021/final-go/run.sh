#!/usr/bin/env bash
# Reproduce the final-go evidence at frozen SHA 51f184a.
# 70-question benchmark (2 trials), follow-up benchmark (2 trials), full SQL audit.
# Requires: . /tmp/go.env, the restore Postgres on 55500, Redis db 10 flushed once,
# and the repo's .env (AI_API_KEY is exported by /tmp/go.env).
set -euo pipefail
cd "$(dirname "$0")"

export REDIS_URL=redis://localhost:56500/10
export PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE=100000
export PUBLIC_CHAT_RATE_LIMIT_PER_DAY=1000000
docker exec kiq-integrate-redis-1 redis-cli -n 10 flushdb

uv run --package knicksiq-api python ../w4-bench/bench_runner.py \
  --trials 2 --per-category 10 --out-dir bench

uv run --package knicksiq-api python ../../../../tools/release/followup_bench.py \
  --trials 2 --out followup/followup_sessions.json

for t in 1 2; do
  uv run --package knicksiq-api python ../factual-audit/audit.py \
    "bench/trial$t.responses.jsonl" --out "audit/trial$t" --label "final-go trial $t"
done

echo "Artifacts written under $(pwd). Re-check audit/flag-verdicts.md against the restore DB."
