#!/usr/bin/env bash
# Rerun the full SQL factual audit on both benchmark trials.
# Needs the local restore container kiq-integrate-postgres-1 (override with KIQ_PSQL).
set -euo pipefail
cd "$(dirname "$0")/../factual-audit"
python3 audit.py ../w4-bench/trial1.responses.jsonl --out ../w4-bench/audit/trial1 \
  --label "w4-bench trial 1"
python3 audit.py ../w4-bench/trial2.responses.jsonl --out ../w4-bench/audit/trial2 \
  --label "w4-bench trial 2"
