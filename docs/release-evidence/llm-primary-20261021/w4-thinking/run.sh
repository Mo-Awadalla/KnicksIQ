#!/usr/bin/env bash
# Run one arm of the reasoning experiment: A (production), B (low), C (medium).
#   ./run.sh A smoke   -> 2 questions, 1 trial, into smoke-A/
#   ./run.sh A full    -> 30 questions, 2 trials, into arm-A/
# Every measured run starts from an empty Redis db 9 (flushed once), so the ledger delta is
# exact. Arms differ only by environment variables; no application file changes.
set -euo pipefail
cd "$(dirname "$0")"
arm="${1:?arm A|B|C}"
mode="${2:?smoke|full}"
. /tmp/go.env
export REDIS_URL=redis://localhost:56500/9
export ANALYST_REASONING_EFFORT=none AI_REASONING_EFFORT=none
export ANALYST_ANSWER_MAX_TOKENS=1600 ANALYST_REVIEW_MAX_TOKENS=3000
if [[ "$arm" == "B" ]]; then
  export ANALYST_REASONING_EFFORT=low AI_REASONING_EFFORT=low
  export ANALYST_ANSWER_MAX_TOKENS=4000 ANALYST_REVIEW_MAX_TOKENS=6000
elif [[ "$arm" == "C" ]]; then
  export ANALYST_REASONING_EFFORT=medium AI_REASONING_EFFORT=medium
  export ANALYST_ANSWER_MAX_TOKENS=4000 ANALYST_REVIEW_MAX_TOKENS=6000
fi
if [[ "$mode" == "smoke" ]]; then
  sample="smoke.json"
  out="smoke-$arm"
  trials=1
else
  sample="sample.json"
  out="arm-$arm"
  trials=2
fi
docker exec kiq-integrate-redis-1 redis-cli -n 9 flushdb >/dev/null
uv run --package knicksiq-api python arm_runner.py \
  --arm "$arm" --out-dir "$out" --sample "$sample" --trials "$trials"
