"""The operations this service supports and the measures a question can name.

An operation is a fixed vocabulary rather than a model's paraphrase: each one is a
calculation the archive can run over its games. `query_operation_decisions` matches an
asked question to one of them; the threshold, aggregation and statistic parsed here mean
the same thing on every path.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

Operation = Literal[
    "player_metric",
    "player_threshold",
    "player_leaderboard",
    "player_game_summary",
    "team_record",
    "win_count",
    "loss_count",
    "game_count",
    "points_total",
    "points_average",
    "points_allowed",
    "average_margin",
    "highest_scoring_game",
    "lowest_scoring_game",
    "lowest_opponent_points_game",
    "largest_win_margin",
    "largest_loss_margin",
    "longest_losing_streak",
    "longest_winning_streak",
    "game_swings",
    "score_threshold",
    "period_scoring",
    "result_split",
]
OPERATIONS = frozenset(Operation.__args__)
TEAM_OPERATIONS = OPERATIONS - {
    "player_metric",
    "player_threshold",
    "player_leaderboard",
    "player_game_summary",
}
# Operations that select games out of a considered population instead of summing it.
RANKING_OPERATIONS = frozenset(
    {
        "game_swings",
        "highest_scoring_game",
        "lowest_scoring_game",
        "lowest_opponent_points_game",
        "largest_win_margin",
        "largest_loss_margin",
        "longest_losing_streak",
        "longest_winning_streak",
        "score_threshold",
    }
)
STREAK_OPERATIONS = frozenset({"longest_losing_streak", "longest_winning_streak"})
# Operations an aggregate cannot answer: they name a subject the question itself fixes.
PLAYER_SUBJECT_OPERATIONS = frozenset(
    {"points_average", "points_total", "largest_win_margin", "largest_loss_margin"}
) | {"highest_scoring_game", "lowest_scoring_game"}
# A broad "how did he do" ask names no measure, so one pinned game is answered by that
# game's own box-score line: the basic statline plus the game's final score. The measures
# are finite, and an ask that names one of its own keeps its own operation instead.
GAME_SUMMARY_STATS: tuple[str, ...] = ("points", "rebounds", "assists")
GAME_SUMMARY_METRICS = frozenset(f"{stat}:game" for stat in GAME_SUMMARY_STATS)
GAME_SCORE_METRIC = "game_score"

ThresholdSubject = Literal["own_points", "opponent_points", "margin", "deficit"]
ThresholdComparator = Literal[">=", ">", "<", "<="]
RequestedAggregation = Literal["average", "total"]


class RequestedMeasure(BaseModel):
    """One supported measure the question itself asks for.

    A compound request carries an ordered list of these, so no measure is silently
    replaced by another one that happened to match first.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: Operation
    stat: str | None = None
    aggregation: RequestedAggregation | None = None


_COMPARATOR_WORDS: dict[str, ThresholdComparator] = {
    "at least": ">=",
    "at most": "<=",
    "more than": ">",
    "over": ">",
    "above": ">",
    "fewer than": "<",
    "less than": "<",
    "under": "<",
    "below": "<",
}
_COMPARATOR_PHRASES: dict[ThresholdComparator, str] = {
    ">=": "at least",
    ">": "more than",
    "<": "fewer than",
    "<=": "at most",
}
_SUBJECT_PHRASES: dict[ThresholdSubject, str] = {
    "own_points": "points",
    "opponent_points": "points",
    "margin": "points",
    "deficit": "points",
}


class ThresholdSpec(BaseModel):
    """A numeric cutoff with the subject it measures and the comparison it uses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: ThresholdSubject
    comparator: ThresholdComparator
    value: int

    def accepts(self, measured: float) -> bool:
        if self.comparator == ">=":
            return measured >= self.value
        if self.comparator == ">":
            return measured > self.value
        if self.comparator == "<=":
            return measured <= self.value
        return measured < self.value

    def describe(self, unit: str | None = None) -> str:
        """Describe the cutoff, naming the counting stat the caller actually measured.

        `unit` (for example "assists") replaces the team-points vocabulary only for a
        player's own counting stat; a margin, deficit or opponent cut-off keeps the subject
        it measures. Without a unit the team rendering still says "points".
        """
        phrase = _COMPARATOR_PHRASES[self.comparator]
        subject = unit if unit and self.subject == "own_points" else _SUBJECT_PHRASES[self.subject]
        return f"{phrase} {self.value} {subject}"


@dataclass(frozen=True)
class OperationDecision:
    """The resolved operation, or the honest reason this ask is refused or clarified."""

    operation: Operation | None = None
    reason: str | None = None
    clarification: str | None = None
    options: tuple[str, ...] = ()
    threshold: ThresholdSpec | None = None
    stat: str | None = None
    measures: tuple[RequestedMeasure, ...] = ()
    aggregation: RequestedAggregation | None = None


_THRESHOLD_ASK = re.compile(
    r"\b(?P<comparator>"
    + "|".join(sorted((re.escape(word) for word in _COMPARATOR_WORDS), key=len, reverse=True))
    + r")\s+(?P<value>\d{1,3})\b"
)
_MARGIN_SUBJECT = re.compile(
    r"\b(?:margin|won by|lost by|win by|lose by|beat\b.*\bby|by the most)\b"
)
_AVERAGE_ASK = re.compile(r"\b(?:average|avg|mean|per game|per appearance)\b")
_TOTAL_ASK = re.compile(r"\b(?:total|totals|combined)\b")
_OPPONENT_SUBJECT = re.compile(r"\b(?:opponents?|allow\w*|held?|holding|hold)\b")
# A follow-up that points back at an earlier game, stretch or possession. It is answerable
# only from a verified anchor, never from the transcript or a season-wide metric.
REFERENTIAL_ASK = re.compile(
    r"\b(?:that|this|the same|the other)\s+game\b"
    r"|\bin that game\b|\bduring it\b|\bduring that\b"
    r"|\bafter that\b|\bbefore that\b"
    r"|\bthat (?:run|stretch|sequence|possession|quarter|half|comeback|surge)\b"
    r"|\bthe final possession\b|\bthe final (?:two minutes|minute)\b"
    r"|\btell me more\b|\bshow me the receipts\b|\bwhat happened next\b"
    r"|\bwho was on the floor then\b|\bwhy was that\b|\bhow long did that\b"
    r"|\bdid they recover\b|\bcompare that with\b"
)
_PLAYER_STAT_ASKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\beffective field[ -]goal\s+(?:percentage|pct|percent)\b"),
        "effective_field_goal_percentage",
    ),
    (
        re.compile(r"\b(?:three|3)[ -]point(?:ers?)?\s+(?:percentage|pct|percent|accuracy)\b"),
        "three_point_percentage",
    ),
    (re.compile(r"\bfrom three\b|\bthree[ -]point shooting\b"), "three_point_percentage"),
    (
        re.compile(r"\bfield[ -]goal\s+(?:percentage|pct|percent)\b"),
        "field_goal_percentage",
    ),
    (re.compile(r"\bfree[ -]throw\s+(?:percentage|pct|percent)\b"), "free_throw_percentage"),
    (re.compile(r"\btrue shooting\b"), "true_shooting_percentage"),
    (re.compile(r"\bassist[ -](?:to[ -])?turnover ratio\b"), "assist_turnover_ratio"),
    (re.compile(r"\btriple[ -]doubles?\b"), "triple_doubles"),
    (re.compile(r"\bdouble[ -]doubles?\b"), "double_doubles"),
)
_STARTS_ASK = re.compile(
    r"\bhow many (?:games|starts)\b[^.?!]*\bstart(?:ed|s)?\b|\bhow many starts\b"
)
PERCENTAGE_STATS = frozenset(
    {
        "field_goal_percentage",
        "three_point_percentage",
        "free_throw_percentage",
        "true_shooting_percentage",
        "effective_field_goal_percentage",
    }
)
RATIO_STATS = frozenset({"assist_turnover_ratio"})


def normalize_text(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()


def is_record_request(question: str) -> bool:
    """A record spans both outcomes; explicit subsets still take precedence."""
    q = normalize_text(question.replace("–", "-").replace("—", "-"))
    if re.search(r"\b(?:only|in)\s+(?:wins?|loss(?:es)?)\b", q):
        return False
    if (
        re.search(r"\bwins?\b", q)
        and re.search(r"\bloss(?:es)?\b", q)
        and re.search(r"\b(?:compare|comparison|versus|vs|better|by average|per game)\b", q)
    ):
        # Comparing the two outcomes needs their split, not one combined record.
        return False
    return bool(
        re.search(r"\brecord\b", q)
        or (re.search(r"\bwins?\b", q) and re.search(r"\bloss(?:es)?\b", q))
    )


def _threshold(q: str) -> ThresholdSpec | None:
    match = _THRESHOLD_ASK.search(q)
    if match is None:
        return None
    if _MARGIN_SUBJECT.search(q):
        subject: ThresholdSubject = (
            "deficit" if re.search(r"\b(?:lost|lose|losing|losses?)\b", q) else "margin"
        )
    elif _OPPONENT_SUBJECT.search(q):
        subject = "opponent_points"
    else:
        subject = "own_points"
    return ThresholdSpec(
        subject=subject,
        comparator=_COMPARATOR_WORDS[match.group("comparator")],
        value=int(match.group("value")),
    )


def _player_stat(q: str) -> str | None:
    for pattern, stat in _PLAYER_STAT_ASKS:
        if pattern.search(q):
            return stat
    return "starts" if _STARTS_ASK.search(q) else None


def player_stat(question: str) -> str | None:
    """The specific canonical shooting stat a question names, if any."""
    return _player_stat(normalize_text(question))


def requested_aggregation(question: str) -> RequestedAggregation | None:
    """The aggregation the question itself asks for, never a model's suggestion."""
    q = normalize_text(question)
    if _TOTAL_ASK.search(q):
        return "total"
    if _AVERAGE_ASK.search(q):
        return "average"
    if re.search(r"\bhow many\b", q):
        return "total"
    return None
