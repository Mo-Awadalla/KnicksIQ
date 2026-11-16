from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MAX_SENTENCE_CHARS = 400
MAX_REJECTED_CHARS = 448

REFERENCE = re.compile(r"\[\[(f\d{1,3})\]\](?=([.!?])?)")
_END = re.compile(r"[.!?\u2026]+[\"'\u201d\u2019)\]]*(?=\s|$)|\n")
_LIST_MARKER_ONLY = re.compile(r"\s*\d{1,2}[.)]")
_LIST_MARKER = re.compile(r"^[ \t]*(?:\d{1,2}[.)]|[-*\u2022])[ \t]+", re.MULTILINE)
_SEASON = re.compile(r"\b2025[-\u2013/](?:20)?26\b")
_ERA = re.compile(r"(?<!\w)(?:['’‘]\d0s|(?:19|20)\d0s)\b", re.IGNORECASE)
_ELISION = re.compile(
    r"['’‘](?:(?:em|cause|cuz|til|bout|round|tis|twas|melo|\d0s)\b(?!['’])|n['’](?=\s))",
    re.IGNORECASE,
)
_QUOTE_END = re.compile(r"['’](?=\W|$)")
_CARDINAL = (
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
    r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|"
    r"trillion|dozen)\b"
)
_WORD_NUMBER = re.compile(_CARDINAL, re.IGNORECASE)
_DIGIT = re.compile(r"\d")
_STAT_UNIT = (
    r"(?:points?(?!\s+(?:guard|forward|god)s?\b)|rebounds?|boards|assists?|dimes|"
    r"steals?|blocks?|turnovers?|minutes?|games?|wins?|losses|threes|triples|buckets?|"
    r"percent(?:age)?|shots?|field goals?|free throws?|all-star teams?|"
    r"championship(?:s|\s+rings?)|rings?|titles?|years?|seasons?)"
)
_STAT_AFTER = re.compile(
    rf"^\W*(?:(?:total|straight|consecutive|career)\s+)?{_STAT_UNIT}\b", re.IGNORECASE
)
_STAT_BEFORE = re.compile(
    r"\b(?:scor(?:e[ds]?|ing)|drop(?:ped|s|ping)?|grab(?:bed|bing|s)?|"
    r"pull(?:ed|s|ing)? down|put(?:s|ting)? up|pour(?:ed|s|ing)? in|"
    r"dish(?:ed|es|ing)?|averag(?:e[ds]?|ing)|record(?:ed|s|ing)?|"
    r"net(?:ted|s|ting)|finish(?:ed|es|ing)? with|won by|lost by|"
    r"beat(?:en|s|ing)?(?:\W+\w+){0,3} by|"
    r"shot|shoot(?:s|ing)?|went for|go(?:es|ing)? for|hung|hang(?:s|ing)?|"
    r"torch(?:ed|es|ing)?(?:\W+\w+){0,3} for|made|make[sd]?|making|hit(?:s|ting)?)"
    r"\b(?:\W+\w+){0,4}\W*$",
    re.IGNORECASE,
)
_VALUE_BEFORE = re.compile(r"\b(?:had|has|have|was|were|is|are)\s*$", re.IGNORECASE)
_VALUE_END = re.compile(r"^\s*[.!?\"'’”)]*\s*$")
_VALUE_CONTEXT = re.compile(
    r"^\s+(?:against|versus|vs\b|on\b|last\b|tonight\b|yesterday\b|"
    r"(?:a|per|every)\s+(?:game|night)\b|in\s+(?:the|that|his|her)\b)",
    re.IGNORECASE,
)
_WORD_RECORD = re.compile(
    rf"\b(?:went|go|goes|going)\s+{_CARDINAL}\s+and\s+{_CARDINAL}", re.IGNORECASE
)
_WORD_SCORE = re.compile(rf"{_CARDINAL}\s*(?:[-–]|-?for-?|\sfor\s)\s*{_CARDINAL}", re.IGNORECASE)
_WORD_YEAR = re.compile(
    rf"\b(?:nineteen|twenty)[-\s]+{_CARDINAL}|\btwo[-\s]+thousand\b",
    re.IGNORECASE,
)
_QUANTITY_FILLER = re.compile(
    r"[\W_]+|\b(?:and|for|just|only|about|exactly|roughly|a|an)\b", re.IGNORECASE
)
_REPORTED_QUANTITY = re.compile(r"\b(?:according to|in the official report)\b", re.IGNORECASE)
_CONCEPT = re.compile(
    r"\b(?:two-way|one-on-one|three-and-d|one-two punch|two-man game|"
    r"three-point(?:ers?| shooting| line)?|zero-sum|one-off|at one point)\b",
    re.IGNORECASE,
)
_TACTIC = re.compile(r"\b(?:two-for-one|fifty-fifty)\b", re.IGNORECASE)
_CLAUSE = re.compile(r"[^,;:!?\u2014()]+")
_NONASSERTIVE = re.compile(
    r"^\s*(?:(?:(?:and|but|or|so|yet|even|only|then|now|well)\s+)?"
    r"(?:if|unless|suppose|imagine|what if|what happens if)\b|"
    r"i(?: would|['’]d) (?:take|prefer|rather have|choose)\b)",
    re.IGNORECASE,
)
_MEMORY_HEDGE = re.compile(
    r"\b(?:if\s+(?:i|you)\s+(?:recall|remember)|if memory serves|"
    r"unless\s+i(?:['’]m| am)\s+(?:wrong|misremembering))\b",
    re.IGNORECASE,
)
_PRESUPPOSED_NUMBER = re.compile(
    rf"(?:['’]s|\b(?:his|her|their|that|the))\s+{_CARDINAL}", re.IGNORECASE
)
_ATTRIBUTION = re.compile(
    r"\b(?:said|says|saying|told|asked|wrote|writes|shouted|yelled|declared|"
    r"insisted|claimed|added|commented|replied|responded|noted|announced|"
    r"remarked|whispered|admitted|tweeted|posted|explained|according to)\b|"
    r"\b(?:came|comes|originated|originates) from\b|"
    r"[:\u2014]\s*[\"'\u201c\u2018]|[\"'\u201d\u2019]\s*[-\u2014]\s*\w|"
    r"\b(?!(?:it|that|there|here|what|who|he|she|this)['’]s\b)"
    r"\w+['’]s(?:\s+\w+){0,3}\s+[\"'\u201c\u2018]",
    re.IGNORECASE,
)
_ATTRIBUTION_CONTEXT = re.compile(
    r"\b(?:exact|verbatim|actual)\s+(?:words?|quotation|quote|remarks?|statement)\b|"
    r"\b\w+['’]s\s+(?:words?|quotation|quote|remarks?|statement)\b",
    re.IGNORECASE,
)
_QUOTE_CONTEXT = re.compile(
    r"\b(?:exact|verbatim|actual)\s+(?:words?|quotation|quote|remarks?|statement)\b|"
    r"\b\w+['’]s\s+(?:words?|quotation|quote|remarks?|statement)\b|"
    r"\b(?:said|says|told|claimed|explained|wrote|posted)\s+"
    r"(?:this|that|these|those|something|anything)\b",
    re.IGNORECASE,
)
_NAMING = r"(?:label|term|phrase|concept|nickname)"
_CRITERION = r"(?:bar|standard|benchmark|definition|criterion)"
_MENTION_PREFIX = re.compile(
    rf"\b(?:call it|the {_NAMING}|{_CRITERION}(?:\s+(?:for|of|is))?)\s*$",
    re.IGNORECASE,
)
_MENTION_SUFFIX = re.compile(rf"\s+(?:{_NAMING}|{_CRITERION})\b", re.IGNORECASE)
_DESCRIPTION_PREFIX = re.compile(r"\b(?:a|an|the|this|that|your)\s*$", re.IGNORECASE)
_DESCRIPTION_SUFFIX = re.compile(r"\s+(?:argument|request|question|update|recap)\b", re.IGNORECASE)
_LABEL = re.compile(r"(?=.{1,48}$)[\w-]+(?:[ -][\w-]+){0,3}")
_COMPARISON_PREFIX = re.compile(r"^\s*(?:(?:but|and|so|well)\s+)?$", re.IGNORECASE)
_COMPARISON_JOIN = re.compile(
    r"\s+(?:and|versus|vs\.?|is\s+not|is\s+different\s+from)\s+",
    re.IGNORECASE,
)
_COMPARISON_END = re.compile(
    r"\s*(?:are|were)\s+(?:different(?:\s+things?|(?:\s+\w+){1,3})?|"
    r"not\s+the\s+same(?:\s+\w+){0,3})\s*[.!?]?\s*$",
    re.IGNORECASE,
)
_COMPARISON_ONLY_NEGATION = re.compile(r"\s+is\s+not\s+$", re.IGNORECASE)
_COMPARISON_TERMINAL = re.compile(r"\s*[.!?]?\s*$")


def _label_comparison(text: str, quotes: _Quotes) -> bool:
    if len(quotes.spans) != 2:
        return False
    (start_a, end_a), (start_b, end_b) = quotes.spans
    first, second = text[start_a + 1 : end_a], text[start_b + 1 : end_b]
    if not _LABEL.fullmatch(first.strip()) or not _LABEL.fullmatch(second.strip()):
        return False
    join = text[end_a + 1 : start_b]
    if not _COMPARISON_PREFIX.fullmatch(text[:start_a]) or not _COMPARISON_JOIN.fullmatch(join):
        return False
    terminal = text[end_b + 1 :]
    if _COMPARISON_ONLY_NEGATION.fullmatch(join):
        return bool(_COMPARISON_TERMINAL.fullmatch(terminal))
    return bool(_COMPARISON_END.fullmatch(terminal))


@dataclass(frozen=True)
class Violation:
    reason: Literal["unbound_number", "unknown_reference", "unsupported_quote"]
    detail: Literal["value", "entity", "metric", "qualifier", "owner", "none"] = "none"
    withheld: str = ""


@dataclass(frozen=True)
class _Quotes:
    spans: tuple[tuple[int, int], ...]
    open: bool


def _quotes(text: str) -> _Quotes:
    spans = []
    start: int | None = None
    closing = ""
    for index, char in enumerate(text):
        before = text[index - 1] if index else ""
        after = text[index + 1] if index + 1 < len(text) else ""
        if char in "'’" and before.isalnum() and after.isalnum():
            continue
        elision = _ELISION.match(text, index) if start is None else None
        if elision and not _ATTRIBUTION.search(text) and not _QUOTE_END.search(text, elision.end()):
            continue
        if start is not None:
            if char == closing:
                spans.append((start, index))
                start = None
            continue
        if char in '"“‘' or (char == "'" and not before.isalnum() and not after.isspace()):
            start = index
            closing = {'"': '"', "“": "”", "‘": "’", "'": "'"}[char]
    return _Quotes(tuple(spans), start is not None)


def _unsupported_quote(text: str, previous: str = "") -> bool:
    quotes = _quotes(text)
    if quotes.open or _QUOTE_CONTEXT.search(text):
        return True
    if quotes.spans and (_ATTRIBUTION.search(text) or _ATTRIBUTION_CONTEXT.search(previous)):
        return True
    if quotes.spans and _label_comparison(text, quotes):
        return False
    return any(
        not (
            _MENTION_PREFIX.search(text[:start])
            or _MENTION_SUFFIX.match(text[end + 1 :])
            or (
                _DESCRIPTION_PREFIX.search(text[:start])
                and _DESCRIPTION_SUFFIX.match(text[end + 1 :])
            )
        )
        for start, end in quotes.spans
    )


def _unbound_number(text: str) -> bool:
    text = _CONCEPT.sub(" ", text)
    text = _TACTIC.sub(
        lambda match: (
            match.group()
            if _STAT_BEFORE.search(text[: match.start()]) or _STAT_AFTER.match(text[match.end() :])
            else " "
        ),
        text,
    )
    if _DIGIT.search(text):
        return True
    for match in _CLAUSE.finditer(text):
        clause = match.group()
        if not _WORD_NUMBER.search(clause):
            continue
        if (
            _NONASSERTIVE.match(clause)
            and not _MEMORY_HEDGE.search(clause)
            and not _PRESUPPOSED_NUMBER.search(clause)
        ):
            continue
        if (
            _WORD_SCORE.search(clause)
            or _WORD_YEAR.search(clause)
            or _WORD_RECORD.search(clause)
            or (_NONASSERTIVE.match(clause) and _PRESUPPOSED_NUMBER.search(clause))
            or _REPORTED_QUANTITY.search(clause)
            or not _QUANTITY_FILLER.sub("", _WORD_NUMBER.sub("", clause))
        ):
            return True
        for number in _WORD_NUMBER.finditer(clause):
            before, after = clause[: number.start()], clause[number.end() :]
            if (
                _STAT_AFTER.match(after)
                or _STAT_BEFORE.search(before)
                or (
                    _VALUE_BEFORE.search(before)
                    and (_VALUE_END.fullmatch(after) or _VALUE_CONTEXT.match(after))
                )
            ):
                return True
    return False
