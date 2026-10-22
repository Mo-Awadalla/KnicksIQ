#!/usr/bin/env bash
# Rerun the replacement factual audit on the three recorded response sets.
# Requires the local restore container kiq-integrate-postgres-1 and psql.
# Usage: ./run.sh
set -euo pipefail
cd "$(dirname "$0")"
OLD_COMMIT="${OLD_COMMIT:-5b585e6}"
LEGACY="$(mktemp -d)"
trap 'rm -rf "$LEGACY"' EXIT

for file in audit.py checks_numeric.py checks_semantic_a.py checks_semantic_b.py \
            checks_policy_20261021.py queries_core.sql queries_events.sql report.py; do
  git show "$OLD_COMMIT:docs/release-evidence/llm-primary-20261021/factual-audit/$file" \
    > "$LEGACY/$file"
done
python3 "$LEGACY/audit.py" ../correctness/acceptance.responses.jsonl > /dev/null

python3 audit.py ../final/budget-16000.trial1.responses.jsonl --out trial1 \
  --old ../final/audit-16000-trial1/verdicts --label "16000 trial 1"
python3 audit.py ../final/budget-16000.trial2.responses.jsonl --out trial2 \
  --old ../final/audit-16000-trial2/verdicts --label "16000 trial 2"
python3 audit.py ../correctness/acceptance.responses.jsonl --out acceptance \
  --old "$LEGACY/verdicts" --label "correctness acceptance"
