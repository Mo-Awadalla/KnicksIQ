"""Proof of the required-fact precision bug fixed in analyst_scoring.fact_ok.

Before the fix, fact_ok called _same_number(value, item) with no written forms, so the
tolerance branch in _same_number was unreachable and 7.6 never matched a label written as
7.57. The committed final held-out row for Miles McBride's playoff average shows the old
behaviour: label 5.63, answer 5.6, required_facts_ok false.

    DB_URL=... uv run --package knicksiq-api python \
        docs/release-evidence/llm-primary-20261021/final/relabel/scorer-precision-proof.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "tools/release"))

from analyst_checks import _same_number  # noqa: E402
from analyst_scoring import score_response  # noqa: E402

case = {
    "id": "precision-proof",
    "category": "exact_statistics",
    "question": "What was the value?",
    "answerable": True,
    "required_facts": ["value 7.57"],
    "required_entities": [],
}
response = {
    "answer": "The archive value was 7.6 rebounds per appearance across the observed games.",
    "citations": [],
    "llm_validated": True,
}
result = score_response(case, response, strict=False)

print("floats only:        ", _same_number(7.6, 7.57))
print("written forms:      ", _same_number(7.6, 7.57, "7.6", "7.57"))
print("required_facts_ok:  ", result["checks"]["required_facts_ok"])
print("required_facts:     ", result["checks"]["required_facts"])

if not _same_number(7.6, 7.57, "7.6", "7.57"):
    raise SystemExit("the precision-aware comparison rejected a compatible value")
if _same_number(7.6, 7.57):
    raise SystemExit("the float-only comparison unexpectedly matched")
if not result["checks"]["required_facts_ok"]:
    raise SystemExit("fact_ok still drops the written forms")
