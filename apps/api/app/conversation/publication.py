from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.conversation.gate import (
    _END,
    _ERA,
    _LIST_MARKER,
    _LIST_MARKER_ONLY,
    _SEASON,
    MAX_REJECTED_CHARS,
    MAX_SENTENCE_CHARS,
    REFERENCE,
    Violation,
    _quotes,
    _unbound_number,
    _unsupported_quote,
)
from app.services.query_operations import normalize_text


@dataclass(frozen=True)
class PublishedClaim:
    authority: str
    text: str
    subject: str | None = None
    value: Decimal | None = None
    metric: str | None = None
    game_ids: frozenset[int] = frozenset()
    game_entities: frozenset[str] = frozenset()

    @property
    def single_game(self) -> bool:
        return len(self.game_ids) == 1


EntityNames = Mapping[str, frozenset[str]]
MAX_REFERENCE_LOOKAHEAD = 48

_METRICS = {
    "point": "points",
    "points": "points",
    "pts": "points",
    "rebound": "rebounds",
    "rebounds": "rebounds",
    "board": "rebounds",
    "boards": "rebounds",
    "assist": "assists",
    "assists": "assists",
    "dime": "assists",
    "dimes": "assists",
    "steal": "steals",
    "steals": "steals",
    "block": "blocks",
    "blocks": "blocks",
    "turnover": "turnovers",
    "turnovers": "turnovers",
    "minute": "minutes",
    "minutes": "minutes",
    "three": "three_pointers_made",
    "threes": "three_pointers_made",
    "three pointer": "three_pointers_made",
    "three pointers": "three_pointers_made",
    "plus minus": "plus_minus",
}
_METRIC_PATTERN = "|".join(sorted(map(re.escape, _METRICS), key=len, reverse=True))
_STATEMENT = re.compile(
    r"^(?P<player>player\d+) (?P<verb>had|has|recorded|finished with|put up|"
    r"scored|dropped|poured in|went for|grabbed|pulled down|dished|dished out) "
    r"scalarvalue"
    rf"(?: (?P<metric>{_METRIC_PATTERN}))?"
    r"(?: (?P<context>(?:against|versus|vs|vs the|against the|versus the) team\d+|"
    r"in that one|in the game against team\d+|in the game against the team\d+))?$"
)
_INFERRED = {
    "scored": "points",
    "dropped": "points",
    "poured in": "points",
    "grabbed": "rebounds",
    "pulled down": "rebounds",
    "dished": "assists",
    "dished out": "assists",
}
_PARTIAL_REF = re.compile(r"(?:\[|\[\[(?:f(?:\d{0,3}(?:\]?)?)?)?)$")
_SCALAR = re.compile(r"(?:[+\-\u2212]\d+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?)(?!\w)")
_NAME_PUNCTUATION = re.compile(r"(?<=[^\W\d_])[-'\u2019\u2010-\u2014](?=[^\W\d_])")


class Publication:
    def __init__(self, facts: Mapping[str, PublishedClaim], lexicon: EntityNames) -> None:
        self.facts = facts
        self.lexicon = lexicon
        self.shown: set[str] = set()
        self.buffer = ""
        self.pending = ""
        self.trailing = ""
        self.previous_sentence = ""

    def _violation(
        self,
        reason: Literal["unbound_number", "unknown_reference", "unsupported_quote"],
        detail: Literal["value", "entity", "metric", "qualifier", "owner", "none"],
        draft: str,
    ) -> Violation:
        self.buffer = self.pending = self.trailing = ""
        return Violation(reason, detail, draft[:MAX_REJECTED_CHARS])

    def _bind(
        self, plain: str, claims: list[PublishedClaim]
    ) -> Literal["value", "entity", "metric", "qualifier", "owner"] | None:
        numeric = _SCALAR.search(plain)
        if numeric is None or _SCALAR.search(plain, numeric.end()) is not None:
            return "value"
        masked = plain[: numeric.start()] + " scalarvalue " + plain[numeric.end() :]
        punctuation = _NAME_PUNCTUATION.sub("", masked)
        if re.search(r"[^\w\s.!]", punctuation) or re.search(r"!(?=\s*\w)", masked):
            return "qualifier"
        normalized = normalize_text(masked)
        aliases: dict[str, frozenset[str]] = {}
        for alias in sorted(self.lexicon, key=len, reverse=True):
            entities = self.lexicon[alias]
            kinds = {entity.partition(":")[0] for entity in entities}
            if len(kinds) != 1 or not kinds <= {"player", "team"}:
                continue
            token = f"{next(iter(kinds))}{len(aliases)}"
            pattern = rf"(?<!\w){re.escape(alias)}(?!\w)"
            normalized, count = re.subn(pattern, token, normalized)
            if count:
                aliases[token] = entities
        match = _STATEMENT.fullmatch(normalized)
        if match is None:
            return "qualifier"
        owners = aliases.get(match["player"], frozenset())
        if len(owners) != 1:
            return "entity"
        owner = next(iter(owners))
        if not claims or any(claim.subject != owner for claim in claims):
            return "owner"
        try:
            value = Decimal(numeric.group().replace("\u2212", "-"))
        except InvalidOperation:
            return "value"
        if any(
            claim.value is None or not claim.value.is_finite() or claim.value != value
            for claim in claims
        ):
            return "value"
        metric = _METRICS.get(match["metric"] or "") or _INFERRED.get(match["verb"])
        implied = _INFERRED.get(match["verb"])
        if metric is None or (implied is not None and metric != implied):
            return "metric"
        if any(claim.metric != metric for claim in claims):
            return "metric"
        context = match["context"] or ""
        if context:
            if any(not claim.single_game for claim in claims):
                return "qualifier"
            if len({claim.game_ids for claim in claims}) != 1:
                return "qualifier"
            team = re.search(r"team\d+", context)
            if team:
                entities = aliases.get(team.group(), frozenset())
                if (
                    len(entities) != 1
                    or "team:NYK" in entities
                    or any(
                        "team:NYK" not in claim.game_entities or not entities <= claim.game_entities
                        for claim in claims
                    )
                ):
                    return "entity"
        return None

    def _compile(self, draft: str) -> str | Violation:
        refs = [match.group(1) for match in REFERENCE.finditer(draft)]
        if any(ref not in self.facts for ref in refs):
            return self._violation("unknown_reference", "none", draft)
        plain = REFERENCE.sub(" ", draft)
        if "[[" in plain or "]]" in plain:
            return self._violation("unknown_reference", "none", draft)
        previous = self.previous_sentence
        if plain.strip():
            self.previous_sentence = plain.strip()[-MAX_SENTENCE_CHARS:]
        checked = _ERA.sub(" ", _SEASON.sub(" ", _LIST_MARKER.sub(" ", plain)))
        if _unsupported_quote(checked, previous):
            return self._violation("unsupported_quote", "none", draft)
        claims = [self.facts[ref] for ref in dict.fromkeys(refs)]
        if _unbound_number(checked):
            detail = self._bind(plain, claims)
            if detail is not None:
                return self._violation("unbound_number", detail, draft)
            output = []
            for claim in claims:
                if claim.authority not in self.shown:
                    self.shown.add(claim.authority)
                    output.append(claim.text)
            return " ".join(output)

        def expand(match: re.Match[str]) -> str:
            claim = self.facts[match.group(1)]
            if claim.authority in self.shown:
                return ""
            self.shown.add(claim.authority)
            text = claim.text
            return text[:-1] if match.group(2) and text.endswith((".", "!", "?")) else text

        return REFERENCE.sub(expand, draft)

    def _drain(self, final: bool) -> list[str | Violation]:
        output: list[str | Violation] = []
        while self.pending or self.buffer:
            if self.pending:
                match = re.match(r"\s*", self.buffer)
                assert match is not None
                whitespace = match.group()
                rest = self.buffer[len(whitespace) :]
                ref = REFERENCE.match(rest)
                if ref:
                    consumed = whitespace + ref.group()
                    self.trailing += consumed
                    self.buffer = self.buffer[len(consumed) :]
                    if len(self.trailing) > MAX_REFERENCE_LOOKAHEAD:
                        output.append(
                            self._violation(
                                "unbound_number", "qualifier", self.pending + self.trailing
                            )
                        )
                        break
                    continue
                if self.trailing and not whitespace and rest[:1] in (".", "!", "?"):
                    self.trailing += rest[0]
                    self.buffer = self.buffer[1:]
                    if len(self.trailing) > MAX_REFERENCE_LOOKAHEAD:
                        output.append(
                            self._violation(
                                "unbound_number", "qualifier", self.pending + self.trailing
                            )
                        )
                        break
                    continue
                if not rest or _PARTIAL_REF.fullmatch(rest):
                    if len(self.trailing) + len(self.buffer) > MAX_REFERENCE_LOOKAHEAD:
                        output.append(
                            self._violation(
                                "unbound_number",
                                "qualifier",
                                self.pending + self.trailing + self.buffer,
                            )
                        )
                        break
                    if not final:
                        break
                    if rest:
                        output.append(
                            self._violation(
                                "unknown_reference",
                                "none",
                                self.pending + self.trailing + self.buffer,
                            )
                        )
                        break
                # A period at a fragment boundary can be part of a decimal.
                if (
                    not self.trailing
                    and not whitespace
                    and rest[:1].isdigit()
                    and self.pending.endswith(".")
                ):
                    self.buffer = self.pending + self.trailing + self.buffer
                    self.pending = self.trailing = ""
                    continue
                draft = self.pending + self.trailing
                self.pending = self.trailing = ""
                result = self._compile(draft)
                if isinstance(result, Violation):
                    output.append(result)
                    break
                if result:
                    output.append(result)
                continue

            cut = None
            for match in _END.finditer(self.buffer):
                if match.end() > MAX_SENTENCE_CHARS:
                    break
                piece = self.buffer[: match.end()]
                if (
                    not piece.strip()
                    or _LIST_MARKER_ONLY.fullmatch(piece.rsplit("\n", 1)[-1])
                    or _quotes(piece).open
                ):
                    continue
                cut = match.end()
                break
            overflow = cut is None and len(self.buffer) > MAX_SENTENCE_CHARS
            if cut is None:
                if len(self.buffer) <= MAX_SENTENCE_CHARS and not final:
                    break
                if len(self.buffer) <= MAX_SENTENCE_CHARS:
                    cut = len(self.buffer)
                elif _quotes(self.buffer[:MAX_SENTENCE_CHARS]).open:
                    output.append(self._violation("unsupported_quote", "none", self.buffer))
                    break
                else:
                    space = self.buffer.rfind(" ", 0, MAX_SENTENCE_CHARS)
                    cut = space if space > 0 else MAX_SENTENCE_CHARS
            piece, self.buffer = self.buffer[:cut], self.buffer[cut:]
            plain = REFERENCE.sub(" ", piece)
            checked = _ERA.sub(" ", _SEASON.sub(" ", _LIST_MARKER.sub(" ", plain)))
            if _unbound_number(checked):
                if overflow:
                    output.append(
                        self._violation(
                            "unbound_number",
                            "qualifier",
                            piece + self.buffer[:MAX_REFERENCE_LOOKAHEAD],
                        )
                    )
                    break
                self.pending = piece
                continue
            result = self._compile(piece)
            if isinstance(result, Violation):
                output.append(result)
                break
            if result and result.strip():
                output.append(result)
        return output

    def feed(self, fragment: str) -> list[str | Violation]:
        self.buffer += fragment
        return self._drain(False)

    def end(self) -> list[str | Violation]:
        result = self._drain(True)
        self.buffer = self.pending = self.trailing = ""
        return result
