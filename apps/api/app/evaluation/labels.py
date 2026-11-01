"""Load immutable expectations and their content-bound review artifacts.

Unresolved inputs block measurement. This module never approves or freezes a proposal.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

Disposition = Literal["answer", "clarify", "refuse"]
DISPOSITIONS: tuple[Disposition, ...] = ("answer", "clarify", "refuse")
_HEX = re.compile(r"^[0-9a-f]{64}$")
FactValue = int | float | dict[str, Any] | str
PROTOCOL = "evaluation-protocol-v2-route-aware"
FREEZE_SCHEMA = "evaluation-freeze-v1"
APPROVAL_SCHEMA = "evaluation-approval-v1"


class LabelError(ValueError):
    """The label artifacts are internally inconsistent or unusable."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class CanonicalFact:
    """One independently proposed typed fact, with the fields it actually asserts."""

    index: int
    metric: str
    value: FactValue
    scope: str
    canonical_evidence_ids: tuple[str, ...]
    numerator: float | None = None
    denominator: float | None = None
    player_name: str | None = None
    appearances: int | None = None
    subject: str | None = None

    @property
    def kind(self) -> str:
        """The kind of the value the fact carries; a value outside the label's own
        vocabulary is unrepresentable rather than silently called a dict."""
        value = self.value
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, dict):
            return "dict"
        if isinstance(value, str):
            return "str"
        raise LabelError(f"canonical fact {self.index} carries an unrepresentable value")

    @classmethod
    def from_dict(cls, index: int, value: dict[str, Any]) -> CanonicalFact:
        try:
            metric = str(value["metric"])
            scope = str(value["scope"])
        except KeyError as exc:
            raise LabelError(f"canonical fact {index} is missing {exc.args[0]}") from exc
        if "value" not in value:
            raise LabelError(f"canonical fact {index} has no value")
        raw = value["value"]
        if isinstance(raw, bool) or not isinstance(raw, (int, float, dict, str)):
            raise LabelError(f"canonical fact {index} has unsupported value type")
        return cls(
            index=index,
            metric=metric,
            value=raw,
            scope=scope,
            canonical_evidence_ids=tuple(
                str(item) for item in value.get("canonical_evidence_ids", [])
            ),
            numerator=_optional_number(value.get("numerator")),
            denominator=_optional_number(value.get("denominator")),
            player_name=str(value["player_name"]) if value.get("player_name") else None,
            appearances=int(value["appearances"]) if value.get("appearances") is not None else None,
            subject=str(value["subject"]) if value.get("subject") else None,
        )


def _optional_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def conversation_context(origin: str, value: Any) -> tuple[dict[str, str], ...]:
    """Read ordered role/content values without rewriting the original request."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise LabelError(f"{origin} has a malformed context")
    turns: list[dict[str, str]] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise LabelError(f"{origin} has a malformed context entry")
        role = entry.get("role")
        content = entry.get("content")
        if (
            set(entry) != {"role", "content"}
            or not isinstance(role, str)
            or role not in {"user", "assistant"}
            or not isinstance(content, str)
            or not content
        ):
            raise LabelError(f"{origin} has an invalid context entry")
        turns.append({"role": role, "content": content})
    return tuple(turns)


@dataclass(frozen=True)
class ExpectationCase:
    id: str
    category: str
    question: str
    disposition: Disposition
    expected_route: str | None
    answerable: bool
    facts: tuple[CanonicalFact, ...]
    canonical_evidence_ids: tuple[str, ...]
    semantic_member: bool
    owner_approved: bool
    notes: tuple[str, ...]
    original_answerable: bool
    original_route: str | None
    context: tuple[dict[str, str], ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExpectationCase:
        expectation = value.get("proposed_expectation")
        if not isinstance(expectation, dict):
            raise LabelError(f"case {value.get('id')} has no proposed_expectation")
        disposition = expectation.get("disposition")
        if disposition not in DISPOSITIONS:
            raise LabelError(f"case {value.get('id')} has invalid disposition {disposition!r}")
        facts = tuple(
            CanonicalFact.from_dict(index, item)
            for index, item in enumerate(expectation.get("canonical_facts") or [])
        )
        return cls(
            id=str(value["id"]),
            category=str(value["category"]),
            question=str(value["question"]),
            disposition=disposition,
            expected_route=expectation.get("expected_route"),
            answerable=bool(expectation.get("answerable")),
            facts=facts,
            canonical_evidence_ids=tuple(
                str(item) for item in expectation.get("canonical_evidence_ids") or []
            ),
            semantic_member=bool(value.get("original_semantic_member")),
            owner_approved=bool(value.get("owner_approved")),
            notes=tuple(str(item) for item in expectation.get("notes") or []),
            original_answerable=bool(value.get("original_answerable")),
            original_route=value.get("original_route"),
            context=conversation_context(
                f"case {value.get('id')}",
                value["context"] if "context" in value else expectation.get("context"),
            ),
        )


@dataclass(frozen=True)
class LabelSet:
    """Every original case plus the identity of the artifacts it was read from."""

    cases: tuple[ExpectationCase, ...]
    questions_sha256: str
    expectations_sha256: str
    declared_case_count: int
    declared_semantic_count: int
    declared_dispositions: dict[str, int]
    labels_sha256: str
    labels_digest_status: Literal["verified", "unverified"]
    owner_approved: int
    frozen: bool
    approval_recorded: bool
    labels_digest_source: str | None = None
    expectations_content_sha256: str = ""
    protocol: str = PROTOCOL
    semantic_ids: tuple[str, ...] = ()
    freeze_sha256: str | None = None
    freeze_problems: tuple[str, ...] = ()
    approval_problems: tuple[str, ...] = ()

    @property
    def identity(self) -> dict[str, str]:
        """The full approved evaluation identity a review must be bound to."""
        return {
            "questions_sha256": self.questions_sha256,
            "expectations_content_sha256": self.expectations_content_sha256,
            "labels_sha256": self.labels_sha256,
            "protocol": self.protocol,
        }

    @property
    def identity_sha256(self) -> str:
        return sha256_bytes(
            json.dumps(self.identity, sort_keys=True, separators=(",", ":")).encode()
        )

    @property
    def case_count(self) -> int:
        return len(self.cases)

    @property
    def answer_cases(self) -> tuple[ExpectationCase, ...]:
        return tuple(case for case in self.cases if case.disposition == "answer")

    @property
    def clarify_cases(self) -> tuple[ExpectationCase, ...]:
        return tuple(case for case in self.cases if case.disposition == "clarify")

    @property
    def refuse_cases(self) -> tuple[ExpectationCase, ...]:
        return tuple(case for case in self.cases if case.disposition == "refuse")

    @property
    def semantic_cases(self) -> tuple[ExpectationCase, ...]:
        return tuple(case for case in self.cases if case.semantic_member)

    @property
    def dispositions(self) -> dict[str, int]:
        counts = {name: 0 for name in DISPOSITIONS}
        for case in self.cases:
            counts[case.disposition] += 1
        return counts

    def by_id(self, case_id: str) -> ExpectationCase:
        for case in self.cases:
            if case.id == case_id:
                return case
        raise KeyError(case_id)


def load_questions(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if not rows:
        raise LabelError(f"{path} contains no questions")
    ids = [str(row.get("id")) for row in rows]
    if len(set(ids)) != len(ids):
        raise LabelError(f"{path} contains duplicate case ids")
    return rows, sha256_bytes(raw)


def load_labels(questions_path: Path, expectations_path: Path) -> LabelSet:
    """Load the immutable question file and the proposed review file together."""
    questions, questions_sha256 = load_questions(questions_path)
    expectations_raw = expectations_path.read_bytes()
    payload = json.loads(expectations_raw.decode("utf-8"))
    cases = tuple(ExpectationCase.from_dict(item) for item in payload.get("cases") or [])
    if not cases:
        raise LabelError("expectations contain no cases")
    question_ids = [str(row["id"]) for row in questions]
    case_ids = [case.id for case in cases]
    if len(set(case_ids)) != len(case_ids):
        raise LabelError("expectations contain duplicate case ids")
    if set(question_ids) != set(case_ids):
        missing = sorted(set(question_ids) - set(case_ids))
        extra = sorted(set(case_ids) - set(question_ids))
        raise LabelError(f"question/expectation ids differ: missing={missing} extra={extra}")
    declared_cases = int(payload.get("case_count") or 0)
    if declared_cases != len(cases):
        raise LabelError(f"declared case_count {declared_cases} != {len(cases)} cases")
    semantic_members = [case for case in cases if case.semantic_member]
    declared_semantic = int(payload.get("semantic_case_count") or 0)
    if declared_semantic != len(semantic_members):
        raise LabelError(
            f"declared semantic_case_count {declared_semantic} != {len(semantic_members)} members"
        )
    declared = dict(payload.get("proposed_dispositions") or {})
    observed = {name: 0 for name in DISPOSITIONS}
    for case in cases:
        observed[case.disposition] += 1
    if declared and {key: int(value) for key, value in declared.items()} != observed:
        raise LabelError(f"declared dispositions {declared} != observed {observed}")
    labels_sha256 = str(payload.get("labels_sha256") or "")
    if not _HEX.match(labels_sha256):
        raise LabelError("labels_sha256 is missing or malformed")
    status, source = _digest_status(labels_sha256, expectations_path, questions_sha256)
    cases = _bind_immutable_questions(cases, questions)
    content_sha256 = _expectations_content_sha256(payload)
    freeze, freeze_problems = _verify_freeze(
        payload.get("freeze"),
        questions_sha256=questions_sha256,
        content_sha256=content_sha256,
        labels_sha256=labels_sha256,
        cases=cases,
    )
    approval_verified, approval_problems = _verify_approval(
        payload.get("owner_approval"),
        labels_sha256=labels_sha256,
        freeze=freeze,
        freeze_sha256=freeze.get("_sha256") if freeze else None,
        case_count=len(cases),
    )
    approved_cases = sum(1 for case in cases if case.owner_approved)
    return LabelSet(
        cases=cases,
        questions_sha256=questions_sha256,
        expectations_sha256=sha256_bytes(expectations_raw),
        declared_case_count=declared_cases,
        declared_semantic_count=declared_semantic,
        declared_dispositions=observed,
        labels_sha256=labels_sha256,
        labels_digest_status=status,
        owner_approved=approved_cases if approval_verified and freeze else 0,
        frozen=bool(freeze),
        approval_recorded=approval_verified,
        labels_digest_source=source,
        expectations_content_sha256=content_sha256,
        semantic_ids=tuple(case.id for case in cases if case.semantic_member),
        freeze_sha256=(freeze.get("_sha256") if freeze else None),
        freeze_problems=freeze_problems,
        approval_problems=approval_problems,
    )


def _digest_status(
    labels_sha256: str, expectations_path: Path, questions_sha256: str
) -> tuple[Literal["verified", "unverified"], str | None]:
    """A digest counts as verified only when a local artifact reproduces it exactly."""
    if labels_sha256 == questions_sha256:
        return "verified", "questions_file"
    candidates: list[Path] = []
    candidates.extend(sorted(expectations_path.parent.glob("*")))
    release_root = _release_evidence_root(expectations_path)
    if release_root is not None:
        candidates.extend(sorted(release_root.glob("*/labels.jsonl")))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            if sha256_bytes(candidate.read_bytes()) == labels_sha256:
                return "verified", str(candidate)
        except OSError:
            continue
    return "unverified", None


def _release_evidence_root(path: Path) -> Path | None:
    for parent in path.parents:
        if parent.name == "release-evidence":
            return parent
    return None


def evaluation_identity(
    labels: LabelSet,
    *,
    mapping_sha256: str,
    documents_sha256: str | None,
    narrative_sha256: str | None = None,
) -> dict[str, str]:
    """The exact artifact identity a recorded review must name."""
    return {
        **labels.identity,
        "mapping_sha256": mapping_sha256,
        "documents_sha256": documents_sha256 or "",
        "narrative_labels_sha256": narrative_sha256 or "",
    }


def identity_digest(identity: dict[str, str]) -> str:
    return sha256_bytes(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())


def _expectations_content_sha256(payload: dict[str, Any]) -> str:
    """The reviewable content: cases and declared totals, not the freeze metadata itself."""
    content = {
        "case_count": payload.get("case_count"),
        "semantic_case_count": payload.get("semantic_case_count"),
        "proposed_dispositions": payload.get("proposed_dispositions"),
        "cases": payload.get("cases"),
    }
    return sha256_bytes(json.dumps(content, sort_keys=True, separators=(",", ":")).encode())


def _bind_immutable_questions(
    cases: tuple[ExpectationCase, ...], questions: list[dict[str, Any]]
) -> tuple[ExpectationCase, ...]:
    """An expectation may refine an answer; it may never change what was asked."""
    original = {str(row["id"]): row for row in questions}
    bound: list[ExpectationCase] = []
    for case in cases:
        row = original[case.id]
        expected_question = str(row.get("question") or "")
        if case.question != expected_question:
            raise LabelError(
                f"case {case.id} changed the immutable question text "
                f"({case.question!r} != {expected_question!r})"
            )
        if case.original_answerable != bool(row.get("answerable")):
            raise LabelError(f"case {case.id} changed the original answerability")
        if case.original_route != row.get("expected_route"):
            raise LabelError(f"case {case.id} changed the original route")
        original_context = conversation_context(f"case {case.id}", row.get("context"))
        if case.context and case.context != original_context:
            raise LabelError(f"case {case.id} changed the immutable conversation context")
        bound.append(replace(case, context=original_context))
    return tuple(bound)


def _verify_freeze(
    payload: Any,
    *,
    questions_sha256: str,
    content_sha256: str,
    labels_sha256: str,
    cases: tuple[ExpectationCase, ...],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """A freeze is only valid when it hashes the artifacts actually loaded."""
    if not isinstance(payload, dict):
        return {}, ("freeze_missing",)
    problems: list[str] = []
    if payload.get("schema") != FREEZE_SCHEMA:
        problems.append("freeze_schema_invalid")
    if payload.get("questions_sha256") != questions_sha256:
        problems.append("freeze_questions_mismatch")
    if payload.get("expectations_content_sha256") != content_sha256:
        problems.append("freeze_expectations_mismatch")
    if payload.get("labels_sha256") != labels_sha256:
        problems.append("freeze_labels_mismatch")
    if payload.get("protocol") != PROTOCOL:
        problems.append("freeze_protocol_mismatch")
    members = tuple(str(item) for item in payload.get("semantic_case_ids") or [])
    declared_members = tuple(case.id for case in cases if case.semantic_member)
    if not members:
        problems.append("freeze_semantic_members_missing")
    elif set(members) != set(declared_members) or len(members) != len(declared_members):
        problems.append("freeze_semantic_members_changed")
    if int(payload.get("case_count") or 0) != len(cases):
        problems.append("freeze_case_count_mismatch")
    if not isinstance(payload.get("frozen_at"), str) or not payload["frozen_at"]:
        problems.append("freeze_timestamp_missing")
    if problems:
        return {}, tuple(problems)
    canonical = {key: value for key, value in payload.items() if key != "_sha256"}
    frozen = dict(payload)
    frozen["_sha256"] = sha256_bytes(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    )
    return frozen, ()


def _verify_approval(
    payload: Any,
    *,
    labels_sha256: str,
    freeze: dict[str, Any],
    freeze_sha256: str | None,
    case_count: int,
) -> tuple[bool, tuple[str, ...]]:
    """An approval must be a hash-bound artifact; a boolean or note never counts."""
    if payload is None:
        return False, ("approval_missing",)
    if not isinstance(payload, dict):
        return False, ("approval_not_artifact",)
    problems: list[str] = []
    if payload.get("schema") != APPROVAL_SCHEMA:
        problems.append("approval_schema_invalid")
    if payload.get("approved") is not True:
        problems.append("approval_not_approved")
    if not str(payload.get("approver") or "").strip():
        problems.append("approval_approver_missing")
    if not str(payload.get("approved_at") or "").strip():
        problems.append("approval_timestamp_missing")
    if payload.get("labels_sha256") != labels_sha256:
        problems.append("approval_labels_mismatch")
    if freeze_sha256 is None:
        problems.append("approval_freeze_unavailable")
    elif payload.get("freeze_sha256") != freeze_sha256:
        problems.append("approval_freeze_mismatch")
    if int(payload.get("case_count") or 0) != case_count:
        problems.append("approval_case_count_mismatch")
    if problems:
        return False, tuple(problems)
    return True, ()
