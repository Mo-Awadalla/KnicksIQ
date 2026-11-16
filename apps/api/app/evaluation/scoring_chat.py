"""Text-visible factual checks; private receipts are never inferred from a reply.

Numeric presence and entity spelling are necessary checks, not proof of attribution.
Scope, paraphrase, abstention and additional assertions require a bound human review.
The original case denominators and gold values remain unchanged.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.evaluation.assertion_entity import declared_player_name
from app.evaluation.assertion_results import AssertionFailure

RETIRED = "inapplicable: public citations retired; owner-approved rubric migration pending"


def _values(value: Any) -> list[int | float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        return [value]
    if isinstance(value, dict):
        return [
            number
            for key, item in value.items()
            if key not in {"nba_game_id", "game_id", "player_id", "team_id", "date"}
            for number in _values(item)
        ]
    if isinstance(value, list):
        return [number for item in value for number in _values(item)]
    return []


def _displayed(value: int | float, tokens: list[Decimal]) -> bool:
    for token in tokens:
        precision = max(0, -int(token.as_tuple().exponent))
        if isinstance(value, int):
            if token == value:
                return True
        elif abs(token - Decimal(str(value))) <= Decimal(1).scaleb(-precision) / 2:
            return True
    return False


def score_chat_case(case: Any, observation: Any, mapping: Any, decisions: Any) -> Any:
    from app.evaluation.scoring_cases import INTEGRITY_CODES, CaseScore, _review_state

    result = CaseScore(case, observation)
    for problem in observation.problems:
        result.failures.append(AssertionFailure(problem.split(":", 1)[0], problem))
    if observation.request.get("message") != case.question:
        result.failures.append(AssertionFailure("request_case_mismatch", case.id))
    # Earlier user messages must have been accepted as real commands, not a context field.
    expected = case.context
    sent = observation.context
    if sent != expected:
        result.failures.append(AssertionFailure("request_context_mismatch", case.id))
    for entry in observation.traces:
        for problem in entry.rank_problems():
            code, _, stage = problem.partition(":")
            result.failures.append(AssertionFailure(code, stage or entry.request_id))
        if entry.data_version != mapping.version:
            result.failures.append(AssertionFailure("trace_release_mismatch", entry.data_version))
        if entry.request_id != observation.sent_request_id:
            result.failures.append(AssertionFailure("trace_request_mismatch", entry.request_id))
    result.integrity = not bool(result.codes & INTEGRITY_CODES)
    decision = decisions.for_case(case.id, observation.response_sha256) if decisions else None
    reviewed, failures, blockers, additions_ok = _review_state(case, observation, decision)
    result.failures.extend(failures)
    result.assertion_blockers.extend(blockers)
    result.reviewed = decision is not None and reviewed
    supported = (
        decision is not None
        and result.reviewed
        and additions_ok
        and not blockers
        and decision.paraphrase == "supported"
        and all(item.decision == "supported" for item in decision.assertions)
        and set(range(len(case.facts))).issubset(
            {index for item in decision.assertions for index in item.canonical_fact_indices}
        )
    )
    disposition = decision is not None and decision.disposition == case.disposition
    if decision is not None and not disposition:
        result.failures.append(AssertionFailure("disposition_mismatch", case.id))
    result.checks.update(
        reviewed=result.reviewed,
        review_disposition_correct=disposition,
        review_content_correct=supported,
        disposition_content=supported and disposition,
    )
    # A review is authoritative for disposition, never a guessed keyword classifier.
    if decision is not None:
        from dataclasses import replace

        result.observation = replace(observation, outcome=decision.disposition)
    else:
        result.assertion_blockers.append("human_review_missing")
    result.checks["citations"] = None
    result.citation_blockers.append(RETIRED)
    if case.disposition == "answer":
        tokens = [
            Decimal(item.replace(",", ""))
            for item in re.findall(
                r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w])",
                re.sub(r"\b20\d{2}-\d{2}(?:-\d{2})?\b", " ", observation.answer),
            )
        ]
        gold = [value for fact in case.facts for value in _values(fact.value)]
        numeric = bool(case.facts) and all(_displayed(value, tokens) for value in gold)
        names = [name for fact in case.facts if (name := declared_player_name(fact))]
        entities = all(
            re.search(r"\b" + re.escape(name) + r"\b", observation.answer, re.I) for name in names
        )
        if not numeric and observation.calculation_audit is None:
            result.failures.append(
                AssertionFailure("numeric_mismatch", "gold value absent from reply")
            )
        if not entities and observation.calculation_audit is None:
            result.failures.append(
                AssertionFailure("entity_mismatch", "gold player absent from reply")
            )
        result.checks.update(
            facts=numeric and entities and supported,
            numeric=numeric,
            entities=entities,
            scope=supported,
            no_additional_facts=supported,
            numeric_attribution=supported,
        )
    if observation.calculation_audit is not None:
        from app.evaluation.scoring_cases import check_calculation_audit

        check_calculation_audit(result, observation, mapping)
        if case.disposition == "answer":
            result.checks["facts"] = supported and result.checks["facts"] is True
            result.checks["scope"] = supported and result.checks["scope"] is True
    if case.disposition == "refuse":
        from app.evaluation.scoring_cases import _dependency_failed

        if _dependency_failed(observation) and not any(
            failure.code == "refusal_dependency_failure" for failure in result.failures
        ):
            result.failures.append(AssertionFailure("refusal_dependency_failure", case.id))
            result.checks["disposition_content"] = False
    result.checks["citations"] = None
    if not result.integrity:
        for key in result.checks:
            if key != "citations":
                result.checks[key] = False
    return result
