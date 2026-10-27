"""Run the false-acceptance runner end to end with a fake reviewer, before spending credits.

The fake reviewer marks every span supported and cites the first sent claim, so accepted
and gate-rejected rows, the per-class table, controls and worst examples are all rendered.
It also records the max_tokens each reviewer call received. No network, no Redis.

    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/w3-revmeasure/offline_report_check.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools" / "release"))

import analyst_review_replay as replay  # noqa: E402
import reviewer_false_acceptance as runner  # noqa: E402
from app.core.config import get_settings  # noqa: E402

EVIDENCE = ROOT / "docs/release-evidence/llm-primary-20261021/reviewer"
SEEN_MAX_TOKENS: list[int] = []


class FakeReviewer:
    max_tokens = 0
    timeout_seconds = 0
    last_metadata: dict = {}

    async def generate(self, *, system: str, user: str) -> str:
        SEEN_MAX_TOKENS.append(self.max_tokens)
        payload = json.loads(user)
        claim_ids = [claim["claim_id"] for claim in payload.get("claims", [])][:1]
        self.last_metadata = {"provider": "fake", "model": "fake", "usage": {"cost": 0.0}}
        review = {
            "assertions": [
                {
                    "text": span,
                    "assertion_type": "factual",
                    "verdict": "supported",
                    "offending_text": None,
                    "supporting_claim_ids": claim_ids,
                    "supporting_evidence_ids": [],
                    "reason": "fake",
                }
                for span in payload["review_spans"]
            ],
            "follow_up_reviews": [],
        }
        return json.dumps(review)


def main() -> None:
    replay.get_llm_adapter = lambda *a, **k: FakeReviewer()
    runner._original_factory = replay.get_llm_adapter
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory() as tmp:
        out, md = Path(tmp) / "fa.json", Path(tmp) / "fa.md"
        sys.argv = [
            "reviewer_false_acceptance.py",
            "--records", str(EVIDENCE / "head-units.jsonl"),
            "--labels", str(EVIDENCE / "labels.json"),
            "--trials", "1",
            "--out", str(out),
            "--markdown", str(md),
        ]  # fmt: skip
        try:
            runner.main()
            checks["report_rendered"] = md.exists()
        except Exception as exc:
            print(f"runner crashed: {type(exc).__name__}: {exc}")
            checks["report_rendered"] = False
        if md.exists():
            text = md.read_text()
            print(text)
            checks["no_false_all_passed_claim"] = "All cases passed" not in text
            checks["gate_blocked_class_rendered"] = "gate-blocked" in text
        if out.exists():
            artifact = json.loads(out.read_text())
            checks["effective_cap_recorded"] = (
                artifact.get("reviewer_max_tokens") == get_settings().analyst_review_max_tokens
            )
    expected = get_settings().analyst_review_max_tokens
    checks["calls_used_production_cap"] = bool(SEEN_MAX_TOKENS) and all(
        value == expected for value in SEEN_MAX_TOKENS
    )
    print(json.dumps({"production_cap": expected, "caps_seen": sorted(set(SEEN_MAX_TOKENS)),
                      "checks": checks}, indent=2))  # fmt: skip
    print("PASS" if all(checks.values()) and len(checks) == 5 else "FAIL")


if __name__ == "__main__":
    main()
