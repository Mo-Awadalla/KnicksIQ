"""Deterministic scoring that makes an analyst answer prove its numbers and its decline.

A number or named entity is backed only by a cited immutable claim or archive receipt. When a
reduced artifact no longer carries citations, a question-scoped archive fallback is used and
labelled as such; it is not claim-level proof.
"""

from __future__ import annotations

import re
from typing import Any

from analyst_checks import (
    CAUSAL,
    COVERAGE_SENTENCE,
    HEDGE,
    NUMBER,
    PAIR,
    SENTENCE,
    Corpus,
    _aliases_for,
    _backed,
    _contains_alias,
    _decline_signals,
    _echo,
    _entity_backed,
    _extract,
    _has_phrase,
    _is_clarification,
    _primary,
    _same_number,
    _sentence_entities,
    claim_corpus,
)


def _fact_numbers(fact: str) -> list[tuple[float, str]]:
    """Fact numbers with their written form, so the precision-aware comparison can run.

    Parses the same NUMBER/PAIR shapes as analyst_checks._numbers_in, which drops the raw
    text. Without the raw text a fact at two decimals can never match a correct answer at
    one decimal even when both round to the same value.
    """
    cleaned = fact.replace(",", "")
    found = [(float(match.group(1)), match.group(1)) for match in NUMBER.finditer(cleaned)]
    for match in PAIR.finditer(fact):
        found.extend((float(item), item) for item in match.groups())
    return found


def category_detail_required(case: dict[str, Any]) -> bool:
    question = str(case.get("question") or "").casefold()
    return case.get("category") == "turning_points" or any(
        word in question for word in ("collapse", "collpase", "collaps")
    )


def score_response(
    case: dict[str, Any],
    response: dict[str, Any],
    *,
    universe: dict[str, tuple[str, ...]] | None = None,
    archive: Any | None = None,
    scoped: Any | None = None,
    strict: bool = True,
    require_claims: bool = False,
) -> dict[str, Any]:
    universe = universe or {}
    raw_citations = response.get("citations")
    reduced = bool(response.get("citations_reduced")) or isinstance(raw_citations, int)
    citations = [] if reduced or not isinstance(raw_citations, list) else raw_citations
    corpus = Corpus(text="", numbers=[], entities=set()) if reduced else claim_corpus(citations)
    answer = str(response.get("answer") or "")
    question = str(case.get("question") or "")
    signals = _decline_signals(answer, response, corpus.claims)
    primary = _primary(signals)
    declined = any(signal in signals for signal in ("field:refused", "phrase:decline"))
    clarification = "structure:clarification" in signals

    factual_corpus = corpus
    evidence_mode = "claims" if corpus.claims else ("receipts" if corpus.receipts else "none")
    if not corpus.claims and scoped is not None:
        factual_corpus = Corpus(
            text=scoped.text,
            numbers=scoped.numbers,
            entities=scoped.entities,
            receipts=corpus.receipts,
        )
        evidence_mode = "archive_index_scoped"
    elif not corpus.claims and archive is not None:
        factual_corpus = Corpus(
            text=archive.text,
            numbers=archive.numbers,
            entities=archive.entities,
            receipts=corpus.receipts,
        )
        evidence_mode = "archive_index" if not corpus.receipts else "receipts+archive"

    sentences = [part for part in SENTENCE.split(answer) if part.strip()]
    unbacked: list[str] = []
    number_total = 0
    for sentence in sentences:
        if COVERAGE_SENTENCE.search(sentence) or _is_clarification(sentence):
            continue
        for token in _extract(sentence):
            if token.kind == "season":
                continue
            number_total += 1
            if not _backed(token, factual_corpus):
                unbacked.append(token.raw)

    detected = _sentence_entities(answer, universe)
    unbacked_entities = sorted(
        entity for entity in detected if not _entity_backed(entity, factual_corpus, universe)
    )
    required_entities = [str(item) for item in case.get("required_entities") or []]
    required_entity_map = {}
    for entity in required_entities:
        required_entity_map[entity] = _aliases_for(entity, universe)
    entities_ok = all(
        any(_contains_alias(answer.casefold(), alias) for alias in aliases)
        for aliases in required_entity_map.values()
    )

    def fact_ok(fact: str) -> bool:
        wanted = _fact_numbers(fact)
        if not wanted:
            return _has_phrase(answer, fact)
        scoped_sentences = sentences
        lowered_fact = fact.casefold()
        for entity in required_entities:
            aliases = _aliases_for(entity, universe)
            if any(_contains_alias(lowered_fact, alias) for alias in aliases):
                matching = [
                    sentence
                    for sentence in sentences
                    if any(_contains_alias(sentence.casefold(), alias) for alias in aliases)
                ]
                if matching:
                    scoped_sentences = matching
                break
        values = [
            (value, token.raw)
            for sentence in scoped_sentences
            for token in _extract(sentence)
            for value in ([token.value] if token.value is not None else list(token.values))
        ]
        return all(
            any(_same_number(value, item, raw, wanted_raw) for item, wanted_raw in values)
            for value, raw in wanted
        )

    facts_ok = all(fact_ok(str(fact)) for fact in case.get("required_facts") or [])
    phrases_ok = all(_has_phrase(answer, phrase) for phrase in case.get("required_phrases") or [])

    hedged = any(HEDGE.search(sentence) and CAUSAL.search(sentence) for sentence in sentences)
    detail_ok = True
    if category_detail_required(case):
        detail_ok = bool(
            re.search(
                r"\b(quarter|period|q[1-4]|1st|2nd|3rd|4th|run|stretch|minutes?|"
                r"\d{4}-\d{2}-\d{2})\b",
                answer,
                re.I,
            )
        )
    echo = _echo(answer, question)
    substantive = (
        corpus.claims > 0 or bool(corpus.receipts) or number_total > len(unbacked) or bool(detected)
    ) and len(answer.strip()) >= 40

    failures: list[str] = []
    if case.get("answerable", True):
        if declined:
            failures.append(f"declined:{primary}")
        if clarification:
            failures.append("clarification")
        if response.get("llm_validated") is False and not declined:
            failures.append("not_validated")
        if not substantive:
            failures.append("not_substantive")
        if unbacked:
            failures.append("unbacked_numbers")
        if unbacked_entities:
            failures.append("unbacked_entities")
        if not facts_ok:
            failures.append("required_facts")
        if not entities_ok:
            failures.append("required_entities")
        if not phrases_ok:
            failures.append("required_phrases")
        if echo:
            failures.append("echo_question")
        if hedged:
            failures.append("hedged_causal")
        if not detail_ok:
            failures.append("missing_turning_detail")
        if require_claims and corpus.claims == 0 and (number_total > 0 or detected):
            failures.append("no_cited_claims")
        elif strict and corpus.claims == 0 and not reduced:
            failures.append("no_cited_claims")
    else:
        if not declined:
            failures.append("not_declined")
        if unbacked or unbacked_entities:
            failures.append("decline_states_unbacked_fact")

    old = response.get("old_meets_expectation")
    if old is None:
        old = (
            response.get("outcome") == "validated"
            if case.get("answerable", True)
            else response.get("outcome") == "validated_declined"
        )
    return {
        "id": case.get("id"),
        "category": case.get("category"),
        "question": question,
        "answerable": bool(case.get("answerable", True)),
        "outcome": response.get("outcome"),
        "old_meets_expectation": bool(old),
        "meets_expectation": not failures,
        "failures": failures,
        "checks": {
            "validated": response.get("llm_validated"),
            "decline_signal": primary,
            "decline_signals": signals,
            "declined": declined,
            "clarification": clarification,
            "substantive": substantive,
            "evidence_mode": evidence_mode,
            "claim_citations": corpus.claims,
            "archive_receipts": corpus.receipts,
            "numbers_total": number_total,
            "unbacked_numbers": unbacked,
            "detected_entities": sorted(detected),
            "unbacked_entities": unbacked_entities,
            "required_facts": case.get("required_facts") or [],
            "required_facts_ok": facts_ok if case.get("required_facts") else None,
            "required_entities_ok": entities_ok if required_entities else None,
            "required_phrases_ok": phrases_ok if case.get("required_phrases") else None,
            "echo_question": echo,
            "hedged_causal": hedged,
            "missing_turning_detail": not detail_ok,
        },
    }
