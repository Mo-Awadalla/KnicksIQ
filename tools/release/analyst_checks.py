"""Pure text, number, entity and decline helpers used by the analyst scorer."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
MONTH_DATE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+"
    r"(\d{1,2})(?:,\s*(\d{4}))?\b",
    re.I,
)
MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
SEASON = re.compile(r"(?<!\d)(?:19|20)\d{2}-\d{2}(?!\d)")
PAIR = re.compile(r"(?<![\w.])([+-]?\d{1,3})\s*-\s*(\d{1,3})(?![\w.])")
NUMBER = re.compile(r"(?<![\w.])([+-]?\d+(?:,\d{3})*(?:\.\d+)?)(%?)(?![\w])")
IDENTIFIER = re.compile(r"\b(?:game|quarter|q|no\.?|number|round|pick)\s*#?\s*$", re.I)

DECLINE = re.compile(
    r"\b(i can(?:'|’)?t|i cannot|can(?:'|’)?t (?:give|provide|answer|predict|verify|confirm)|"
    r"cannot (?:give|provide|answer|predict|confirm)|not able to|unable to|"
    r"do(?:es)? not (?:include|cover|contain|have|support)|doesn(?:'|’)?t (?:include|cover|"
    r"contain|have|support)|no (?:live|future|current|injury|trade)|outside the archive|"
    r"not in the (?:available )?archive|known gaps?)\b",
    re.I,
)
COVERAGE_SENTENCE = re.compile(
    r"\b(can(?:'|’)?t|cannot|unable|no live|not include|does not include|doesn(?:'|’)?t include|"
    r"does not cover|doesn(?:'|’)?t cover|outside the archive|not in the archive|known gaps?|"
    r"archive covers|available (?:data|archive) (?:covers|includes)|coverage is incomplete|"
    r"player rows are missing|recorded data)\b",
    re.I,
)
CLARIFY = re.compile(
    r"\b(which (?:team|player|game|quarter|season|one)|do you mean|did you mean|"
    r"could you (?:specify|clarify)|can you (?:specify|clarify)|once you (?:name|specify)|"
    r"should .{0,30} mean|please specify|who do you mean)\b",
    re.I,
)
HEDGE = re.compile(
    r"\b(probably|likely|may have|might have|perhaps|seems? to|appears? to|arguably|"
    r"could have|possibly)\b",
    re.I,
)
CAUSAL = re.compile(
    r"\b(because|due to|caused|led to|resulted from|result of|will|would|should|"
    r"better|worse|improved|declined|momentum)\b",
    re.I,
)
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
WORD = re.compile(r"[a-z0-9']+")
STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "at",
    "by",
    "with",
    "from",
    "is",
    "are",
    "was",
    "were",
    "did",
    "do",
    "does",
    "how",
    "what",
    "which",
    "who",
    "when",
    "where",
    "why",
    "this",
    "that",
    "these",
    "those",
    "it",
    "their",
    "they",
    "he",
    "she",
    "his",
    "her",
    "them",
    "as",
    "than",
    "be",
    "been",
    "has",
    "have",
    "had",
    "not",
    "no",
    "over",
    "per",
}


@dataclass(frozen=True)
class Token:
    raw: str
    kind: str
    value: float | None = None
    values: tuple[float, ...] = ()


@dataclass
class Corpus:
    text: str
    numbers: list[float]
    entities: set[str]
    claims: int = 0
    receipts: int = 0


def _numbers_in(value: Any) -> list[float]:
    found: list[float] = []
    if isinstance(value, bool) or value is None:
        return found
    if isinstance(value, (int, float)):
        found.append(float(value))
    elif isinstance(value, str):
        for match in NUMBER.finditer(value.replace(",", "")):
            found.append(float(match.group(1)))
        for match in PAIR.finditer(value):
            found.extend(float(item) for item in match.groups())
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_numbers_in(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_numbers_in(item))
    return found


def _add_dates(text: str, numbers: list[float], dates: set[str]) -> None:
    for match in DATE.finditer(text):
        raw = match.group(0)
        dates.add(raw)
        numbers.extend(float(part) for part in match.groups())
    for match in MONTH_DATE.finditer(text):
        month = MONTHS[match.group(1)[:3].casefold()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else 0
        dates.add(f"{year:04d}-{month:02d}-{day:02d}" if year else f"{month:02d}-{day:02d}")
        numbers.extend([float(day), float(month)] + ([float(year)] if year else []))


def claim_corpus(citations: list[dict[str, Any]]) -> Corpus:
    parts: list[str] = []
    numbers: list[float] = []
    entities: set[str] = set()
    claims = receipts = 0
    for citation in citations:
        metadata = citation.get("metadata") or {}
        claim = metadata.get("claim")
        if isinstance(claim, dict):
            claims += 1
            parts.extend(
                str(claim.get(key) or "")
                for key in ("statement", "subject_id", "metric_id", "unit", "population")
            )
            parts.append(str(claim.get("filters") or ""))
            parts.append(str(claim.get("window") or ""))
            numbers.extend(_numbers_in(claim))
            subject = str(claim.get("subject_id") or "")
            if subject.startswith("player:"):
                entities.add(subject)
            filters = claim.get("filters") or {}
            if isinstance(filters, dict):
                entities.update(str(value) for value in filters.values() if value)
        else:
            receipts += 1
        for key in ("claim", "title", "source_name"):
            value = citation.get(key)
            if value:
                parts.append(str(value))
                numbers.extend(_numbers_in(value))
    text = " ".join(parts).casefold()
    dates: set[str] = set()
    _add_dates(text, numbers, dates)
    for date in dates:
        numbers.extend(float(part) for part in re.findall(r"\d+", date))
    return Corpus(text=text, numbers=numbers, entities=entities, claims=claims, receipts=receipts)


def _extract(text: str) -> list[Token]:
    tokens: list[Token] = []
    occupied: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= left or start >= right for left, right in occupied)

    for match in SEASON.finditer(text):
        if free(match.start(), match.end()):
            occupied.append(match.span())
            tokens.append(Token(match.group(0), "season"))
    for match in DATE.finditer(text):
        if free(match.start(), match.end()):
            occupied.append(match.span())
            tokens.append(Token(match.group(0), "date"))
    for match in MONTH_DATE.finditer(text):
        if free(match.start(), match.end()):
            occupied.append(match.span())
            tokens.append(Token(match.group(0), "date"))
    for match in PAIR.finditer(text):
        if free(match.start(), match.end()):
            occupied.append(match.span())
            values = tuple(float(item) for item in match.groups())
            tokens.append(Token(match.group(0), "pair", values=values))
    for match in NUMBER.finditer(text):
        if not free(match.start(), match.end()):
            continue
        prefix = text[max(0, match.start() - 14) : match.start()]
        if IDENTIFIER.search(prefix):
            continue
        raw, percent = match.group(1), match.group(2)
        value = float(raw.replace(",", ""))
        tokens.append(Token(raw + percent, "percent" if percent else "number", value=value))
    return tokens


def _same_number(left: float, right: float, left_raw: str = "", right_raw: str = "") -> bool:
    if math.isclose(left, right, rel_tol=0, abs_tol=1e-9):
        return True
    left_places = len(left_raw.split(".")[1]) if "." in left_raw else 0
    right_places = len(right_raw.split(".")[1]) if "." in right_raw else 0
    places = min(left_places, right_places) if left_places or right_places else 0
    tolerance = 0.5 * 10 ** (-places) if places else 0.0
    return abs(left - right) <= tolerance + 1e-9


def _backed(token: Token, corpus: Corpus) -> bool:
    if token.kind == "season":
        return True
    if token.kind == "date":
        if token.raw.casefold() in corpus.text:
            return True
        date = DATE.fullmatch(token.raw)
        if date:
            parts = [float(part) for part in date.groups()]
            return all(any(_same_number(part, item) for item in corpus.numbers) for part in parts)
        month = MONTH_DATE.fullmatch(token.raw)
        if month:
            day = float(month.group(2))
            month_number = float(MONTHS[month.group(1)[:3].casefold()])
            year = float(month.group(3)) if month.group(3) else None
            values = [day, month_number] + ([year] if year else [])
            if all(any(_same_number(value, item) for item in corpus.numbers) for value in values):
                return True
            iso = f"{int(year):04d}-{int(month_number):02d}-{int(day):02d}" if year else ""
            return bool(iso and iso in corpus.text)
        return False
    if token.kind == "pair":
        return token.raw.replace(" ", "") in corpus.text.replace(" ", "") or all(
            any(_same_number(value, item) for item in corpus.numbers) for value in token.values
        )
    if token.value is None:
        return True
    if token.raw.casefold() in corpus.text:
        return True
    candidates = [token.value]
    if token.kind == "percent":
        candidates.append(token.value / 100)
    else:
        candidates.append(token.value / 100)
    return any(
        _same_number(candidate, item, token.raw.rstrip("%"), "")
        for candidate in candidates
        for item in corpus.numbers
    )


def _contains_alias(text: str, alias: str) -> bool:
    token = alias.casefold()
    if not token:
        return False
    if " " not in token:
        return re.search(rf"\b{re.escape(token)}\b", text) is not None
    return token in text


def _aliases_for(entity: str, universe: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    if entity in universe:
        return universe[entity]
    for aliases in universe.values():
        if any(alias.casefold() == entity.casefold() for alias in aliases):
            return aliases
    return (entity,)


def _sentence_entities(sentence: str, universe: dict[str, tuple[str, ...]]) -> set[str]:
    lowered = sentence.casefold()
    found = set()
    for canonical, aliases in universe.items():
        hit = False
        for alias in aliases:
            if " " in alias:
                hit = alias.casefold() in lowered
            else:
                # Single-token aliases must be capitalised, so "post" in "post-All-Star" is
                # not the player Post and "eason" in "season" is not the player Eason.
                hit = re.search(rf"\b{re.escape(alias)}\b", sentence) is not None
            if hit:
                found.add(canonical)
                break
    return found


def _entity_backed(entity: str, corpus: Corpus, universe: dict[str, tuple[str, ...]]) -> bool:
    aliases = _aliases_for(entity, universe)
    if any(_contains_alias(corpus.text, alias) for alias in aliases):
        return True
    if entity.startswith("player:"):
        return entity in corpus.entities
    return False


def _phrase_variants(phrase: str) -> tuple[str, ...]:
    lowered = phrase.casefold()
    variants = [lowered]
    for ordinal, digit, suffix in (
        ("first", "1", "st"),
        ("second", "2", "nd"),
        ("third", "3", "rd"),
        ("fourth", "4", "th"),
    ):
        if lowered.startswith(ordinal):
            variants.extend(
                [
                    lowered.replace(ordinal, f"{digit}{suffix}", 1),
                    lowered.replace(ordinal, f"q{digit}", 1),
                    lowered.replace(ordinal, digit, 1),
                ]
            )
    return tuple(variants)


def _has_phrase(answer: str, phrase: str) -> bool:
    lowered = answer.casefold()
    return any(variant in lowered for variant in _phrase_variants(phrase))


def _tokens(text: str) -> set[str]:
    return {
        word for word in WORD.findall(text.casefold()) if word not in STOPWORDS and len(word) > 1
    }


def _echo(answer: str, question: str) -> bool:
    question_words = _tokens(question)
    answer_words = _tokens(answer)
    if not question_words:
        return False
    return (
        len(question_words & answer_words) / len(question_words) >= 0.9
        and len(answer_words) <= len(question_words) + 2
    )


def _decline_signals(answer: str, response: dict[str, Any], claims: int) -> list[str]:
    signals = []
    if response.get("refused"):
        signals.append("field:refused")
    if response.get("degraded"):
        signals.append("field:degraded")
    validated = response.get("llm_validated")
    if validated is False and not response.get("refused"):
        signals.append("field:unvalidated")
    warnings = " ".join(str(item) for item in response.get("warnings") or []).casefold()
    if "review" in warnings and ("reject" in warnings or "could not be verified" in warnings):
        signals.append("field:warning_fallback")
    if _is_clarification(answer):
        signals.append("structure:clarification")
    if DECLINE.search(answer) and (claims == 0 or len(answer) < 600):
        signals.append("phrase:decline")
    return signals


def _is_clarification(answer: str) -> bool:
    stripped = answer.strip()
    return stripped.endswith("?") or bool(CLARIFY.search(stripped))


def _primary(signals: list[str]) -> str | None:
    order = (
        "field:refused",
        "field:degraded",
        "field:warning_fallback",
        "field:unvalidated",
        "structure:clarification",
        "phrase:decline",
    )
    for name in order:
        if name in signals:
            return name
    return None
