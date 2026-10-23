#!/usr/bin/env bash
# Run the full SQL factual audit on both trials of every arm.
# One audit version is used for all arms; AUDIT_DIR selects it (default: this worktree's copy).
# Needs the local restore container kiq-integrate-postgres-1 (override with KIQ_PSQL).
set -euo pipefail
cd "$(dirname "$0")"
AUDIT_DIR="${AUDIT_DIR:-../factual-audit}"
for arm in A B C; do
  for trial in 1 2; do
    python3 "$AUDIT_DIR/audit.py" "arm-$arm/trial$trial.responses.jsonl" \
      --out "arm-$arm/audit/trial$trial" --label "arm $arm trial $trial"
  done
done
