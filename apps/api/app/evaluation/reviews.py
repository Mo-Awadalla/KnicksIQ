"""Recorded per-assertion reviewer decisions, bound to the exact artifacts they judged.

Natural-language assertion quality is not decided by a regex. A recorded human
decision is required for every one of the original cases, bound to the full
evaluation identity (questions, expectations content, labels digest, protocol,
mapping and document identity) and to the exact response digest. The review must
also be structurally complete: an answer review without assertions, with
out-of-range or missing canonical fact references, or with assertion spans that
are not verifiable cannot pass. A missing, stale or partial record leaves the
affected metric unmeasured rather than passing. Nothing in this module creates
an approval.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

SCHEMA = "evaluation-review-decisions-v2"
_VERDICTS = frozenset({"supported", "unsupported", "insufficient_evidence"})


class ReviewError(ValueError):
    """Recorded review decisions are unusable or bound to a different evaluation."""


@dataclass(frozen=True)
class AssertionDecision:
    text: str
    decision: Literal["supported", "unsupported", "insufficient_evidence"]
    canonical_fact_indices: tuple[int, ...]
    evidence: str


@dataclass(frozen=True)
class CaseDecision:
    case_id: str
    response_sha256: str
    disposition: Literal["answer", "clarify", "refuse"]
    assertions: tuple[AssertionDecision, ...]
    paraphrase: Literal["supported", "unsupported", "insufficient_evidence"]


@dataclass(frozen=True)
class DecisionRecord:
    evaluation_identity_sha256: str
    dataset_sha256: str
    reviewer: str
    reviewed_at: str
    file_sha256: str
    cases: dict[str, CaseDecision]

    def for_case(self, case_id: str, response_sha256: str) -> CaseDecision | None:
        decision = self.cases.get(case_id)
        if decision is None or decision.response_sha256 != response_sha256:
            return None
        return decision


def load_decisions(
    path: Path,
    *,
    identity_sha256: str,
    questions_sha256: str,
    cases: dict[str, tuple[int, str]],
) -> DecisionRecord:
    """Load decisions and validate them against the exact cases they claim to judge.

    ``cases`` maps case id to ``(canonical fact count, expected disposition)``.
    """
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ReviewError(f"unexpected review schema {payload.get('schema')!r}")
    if str(payload.get("evaluation_identity_sha256") or "") != identity_sha256:
        raise ReviewError("review decisions are bound to a different evaluation identity")
    if str(payload.get("dataset_sha256") or "") != questions_sha256:
        raise ReviewError("review decisions are bound to a different question digest")
    reviewer = str(payload.get("reviewer") or "")
    if not reviewer:
        raise ReviewError("review decisions have no reviewer")
    reviewed_at = str(payload.get("reviewed_at") or "")
    try:
        datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewError("review decisions have no valid reviewed_at") from exc
    decisions: dict[str, CaseDecision] = {}
    for item in payload.get("cases") or []:
        decision = _case(item, cases)
        if decision.case_id in decisions:
            raise ReviewError(f"duplicate reviewed case {decision.case_id}")
        decisions[decision.case_id] = decision
    return DecisionRecord(
        evaluation_identity_sha256=identity_sha256,
        dataset_sha256=questions_sha256,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        cases=decisions,
    )


def _case(item: dict[str, Any], cases: dict[str, tuple[int, str]]) -> CaseDecision:
    case_id = str(item.get("case_id") or "")
    response_sha256 = str(item.get("response_sha256") or "")
    disposition = item.get("disposition")
    if not case_id or not response_sha256:
        raise ReviewError("reviewed case lacks case_id or response digest")
    if case_id not in cases:
        raise ReviewError(f"reviewed case {case_id} is not in the evaluation set")
    fact_count, _ = cases[case_id]
    if disposition not in {"answer", "clarify", "refuse"}:
        raise ReviewError(f"reviewed case {case_id} has invalid disposition")
    assertions: list[AssertionDecision] = []
    for raw in item.get("assertions") or []:
        verdict = raw.get("decision")
        if verdict not in _VERDICTS:
            raise ReviewError(f"reviewed case {case_id} has invalid assertion verdict")
        text = str(raw.get("text") or "")
        if not text.strip():
            raise ReviewError(f"reviewed case {case_id} has an assertion with no span")
        evidence = str(raw.get("evidence") or "")
        if verdict in {"supported", "unsupported"} and not evidence:
            raise ReviewError(f"reviewed case {case_id} has a decided assertion without evidence")
        indices = tuple(int(value) for value in raw.get("canonical_fact_indices") or [])
        if verdict == "supported":
            if not indices and disposition == "answer":
                raise ReviewError(
                    f"reviewed case {case_id} has a supported assertion with no canonical fact"
                )
            if any(index < 0 or index >= fact_count for index in indices):
                raise ReviewError(
                    f"reviewed case {case_id} references canonical fact "
                    f"{max(indices)} of {fact_count}"
                )
        assertions.append(AssertionDecision(text, verdict, indices, evidence))
    paraphrase = item.get("paraphrase")
    if disposition == "answer" and paraphrase == "supported" and not assertions:
        raise ReviewError(f"answer case {case_id} was reviewed without any assertion")
    if paraphrase not in _VERDICTS:
        raise ReviewError(f"reviewed case {case_id} has no paraphrase verdict")
    return CaseDecision(case_id, response_sha256, disposition, tuple(assertions), paraphrase)
