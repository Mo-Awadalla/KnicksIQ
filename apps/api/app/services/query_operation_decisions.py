"""Resolve metric intent and evidence prerequisites against the typed request scope."""

from __future__ import annotations

import re
from typing import Literal

from app.services.query_operations import (
    PERCENTAGE_STATS,
    PLAYER_SUBJECT_OPERATIONS,
    RATIO_STATS,
    Operation,
    OperationDecision,
    RequestedAggregation,
    RequestedMeasure,
    _player_stat,
    _threshold,
    is_record_request,
    normalize_text,
    requested_aggregation,
)

UNSUPPORTED_LIVE = (
    "I can only answer from the archived Knicks games in this release. I have no live, "
    "current, future, injury, trade, standings or betting coverage."
)
UNSUPPORTED_MARGIN_WITHOUT_COUNT = (
    "The archive counts games against a numeric cutoff when the question asks how many. "
    "Ask how many games crossed it, or ask for a scoring extreme."
)

_LOSS_WORDS = r"(?:loss|losses|losing|lost)"
_STREAK_LOSS = re.compile(rf"\b{_LOSS_WORDS}\b.*\bstreaks?\b|\bstreaks?\b.*\b{_LOSS_WORDS}\b")
_STREAK_WIN = re.compile(r"\b(?:winning|win|wins|won)\b.*\bstreaks?\b|\bstreaks?\b.*\bwinning\b")
_LARGEST_LOSS = re.compile(
    r"\b(?:worst|biggest|largest)\s+(?:loss|losses|defeat)\b"
    r"|\blost by the most\b"
    r"|\bbeat the knicks by (?:the )?most\b"
    r"|\b(?:beat the knicks|knicks lost|lost to)\b.*\b(?:biggest|largest)\s+margin\b"
    r"|\b(?:biggest|largest)\s+margin\b.*\b(?:loss|losses|defeat)\b"
)
_LARGEST_WIN = re.compile(
    r"\b(?:best|biggest|largest)\s+(?:win|wins|victory)\b"
    r"|\bbiggest blowout\b"
    r"|\bwon by the most\b"
    r"|\b(?:best|biggest|largest)\s+(?:game|games)\b"
    r"|\b(?:biggest|largest)\s+margin\b.*\b(?:win|wins|victory)\b"
)
_BEST_DEFENSIVE = re.compile(
    r"\b(?:best|strongest)\s+defensive\s+(?:game|performance|outing)\b"
    r"|\b(?:fewest|least)\s+points\s+allowed\b"
)
_COUNT_ASK = re.compile(r"\b(?:how many|number of|count(?:ing)?)\b")
_MARGIN_MEASURE = re.compile(r"\b(?:margin|margins|point differential|differential)\b")
_LEADER_ASK = re.compile(
    r"\bwho led\b|\bwho leads\b|\bwho lead\b|\bled the (?:team|knicks|club)\b"
    r"|\bteam leader\b|\bwho (?:had|has|scored|grabbed|recorded|made) the most\b"
    r"|\bwhich player\b.*\b(?:most|led)\b|\btop scorer\b"
)
_SCORING_WORD = re.compile(r"\b(?:scor\w*|points?)\b")
_SHOOTING_WORD = re.compile(r"\b(?:shoot\w*|field goals?|fg)\b")
_WINS = re.compile(r"\bwins?\b")
_LOSSES = re.compile(r"\bloss(?:es)?\b")
_RANKING_WORD = re.compile(
    r"\b(?:most|best|worst|longest|highest|lowest|fewest|biggest|largest|top|rank|ranked)\b"
)
_NARRATIVE_ASK = re.compile(
    r"\b(?:walk me through|tell the story|what happened|what changed|what decided|"
    r"explain|influence[sd]?|affect(?:ed|s)?|shape[ds]?|decided|good game|was that|"
    r"what was the score|which (?:game|one) do you mean|immediately after|key sequence|"
    r"the final (?:two minutes|possession|minute)|where did .{0,24}turn|"
    r"comebacks?|came back|come from behind|lead changes?|collapses?|collpase|"
    r"drought|momentum|clutch|turning point|decisive|broke open|lose control|"
    r"lose the lead|lost the lead|stall\w*|swung the|started the comeback|cost the knicks)\b"
    r"|\bhow did .{0,40}\b(?:close|answer|respond|erase|recover|protect|stall)\b"
    r"|\bwhy (?:did|was|were|do|does)\b"
    r"|\bwho was on the floor\b|\bhow long did that run\b|\bwhat did .{0,30} do during\b"
    r"|\bshow me the receipts\b"
)
_RUN_ASK = re.compile(r"\b(?:runs?|stretch(?:es)?)\b")
_DEFINITION_ASK = re.compile(
    r"\bclose games?\b|\bblowouts?\b|\boffense or (?:the )?defense\b"
    r"|\bstronger\b|\bback[ -]to[ -]backs?\b"
)
_COMPARATIVE_ASK = re.compile(r"\b(?:better|worse)\b")
_LIVE_ASK = re.compile(
    r"\b(?:live|tonight|today|tomorrow|yesterday|currently|upcoming|forecast)\b"
    r"|\b(?:injured?|injuries|injury)\b|\btrades?\b|\btraded\b|\bsigning(?:s)?\b"
    r"|\bbetting\b|\bodds\b|\bspread\b|\bstandings\b|\bplayoff picture\b"
    r"|\bnext (?:game|season)\b|\bwill (?:the knicks|they|he|she)\b"
    r"|\b(?:202[7-9]|20[3-9]\d)(?:-\d{2}-\d{2})?\b"
)
_HOW_DID_DO = re.compile(r"\bhow did\b")
_DO_VERB = re.compile(r"\b(?:do|done|perform|performed|fare|fared)\b")
_PERFORMANCE_ASK = re.compile(
    r"\bwhat did\b.{0,60}\b(?:do|put up|finish with|end with)\b"
    r"|\bhow did\b.{0,60}\b(?:do|play|perform|fare|look)\b"
    r"|\bhow (?:was|were)\b.{0,40}\b(?:game|night|performance|outing)\b"
    r"|\bhow good was\b"
    r"|\b(?:stat ?line|box score)\b"
    r"|\bwhat (?:was|were)\b.{0,40}\b(?:stats?|numbers)\b"
    r"|\b(?:play|played|playing)\s+(?:well|good|great|bad|poorly)\b"
)
_SEQUENCE_ASK = re.compile(
    r"\b(?:key|decisive)\s+(?:sequence|sequences|possessions?|plays?|moments?)\b"
    r"|\bsequence\b|\bturning point\b|\bmomentum\b|\bclutch\b"
    r"|\b(?:runs?|stretches?|comebacks?|came back|come from behind)\b"
    r"|\b(?:lead changes?|collapses?|drought|stall\w*|broke open|broke it open)\b"
    r"|\bfinal (?:two minutes|possessions?|minute)\b"
    r"|\bwhat changed\b|\bwhat (?:decided|swung|shaped)\b|\bswung the\b"
    r"|\b(?:walk me through|tell the story)\b"
    r"|\bhow did\b.{0,40}\b(?:close|answer|respond|erase|recover|protect|stall|lose the lead)\b"
    r"|\bwhy (?:did|was|were|do|does)\b"
)

_EVENT_INTERVAL = re.compile(
    r"\b(?:first|last|final|opening|closing)\s+"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\s+"
    r"(?:minutes?|mins?|seconds?|secs?)\b"
    r"|\b(?:first|last|final|opening|closing)\s+minutes?\b"
    r"|\b(?:first|last|final|opening|closing)\s+seconds?(?!\s+(?:half|quarter|period)s?)\b"
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\s+"
    r"(?:minutes?|seconds?)\s+(?:left|remaining|to play|to go)\b"
)
_MEASURE_CLAUSE = re.compile(r"[,;]|\band\b", re.IGNORECASE)
_POINTS_ALLOWED = re.compile(r"\bpoints? allowed\b|\ballowed\b")


def _requested_measures(question: str) -> tuple[RequestedMeasure, ...]:
    """Keep each raw clause's own operation and aggregation."""
    aggregation = requested_aggregation(question)
    if aggregation is None:
        return ()
    found: list[RequestedMeasure] = []
    for clause in _MEASURE_CLAUSE.split(question):
        clause_aggregation = requested_aggregation(clause) or aggregation
        normalized = normalize_text(clause)
        if _MARGIN_MEASURE.search(normalized):
            candidate = RequestedMeasure(operation="average_margin", aggregation=clause_aggregation)
        elif _POINTS_ALLOWED.search(normalized) and _SCORING_WORD.search(normalized):
            candidate = RequestedMeasure(operation="points_allowed", aggregation=clause_aggregation)
        elif _SCORING_WORD.search(normalized):
            candidate = RequestedMeasure(
                operation=("points_average" if clause_aggregation == "average" else "points_total"),
                aggregation=clause_aggregation,
            )
        else:
            continue
        if candidate not in found:
            found.append(candidate)
    return tuple(found) if len(found) > 1 else ()


_FIXED_AGGREGATION: dict[str, RequestedAggregation] = {
    "points_average": "average",
    "average_margin": "average",
    "points_total": "total",
}
_DEFAULT_AGGREGATION: dict[str, RequestedAggregation] = {"points_allowed": "average"}


def _operation_aggregation(
    operation: Operation | None, requested: RequestedAggregation | None
) -> RequestedAggregation | None:
    if operation in _FIXED_AGGREGATION:
        return _FIXED_AGGREGATION[operation]
    return requested or _DEFAULT_AGGREGATION.get(operation or "")


def _clarify_run(*, pinned_game: bool) -> OperationDecision:
    if pinned_game:
        clarification = (
            "The game is anchored, but a scoring run still needs one definition. Which one?"
        )
    else:
        clarification = (
            "A scoring run needs a game, the event interval it covers (which minutes or "
            "possessions) and one definition. Name the game and interval, then choose the "
            "definition."
        )
    return OperationDecision(
        clarification=clarification,
        options=("largest unanswered scoring run", "largest net margin change in a fixed window"),
    )


def _clarify_narrative(q: str) -> OperationDecision:
    if re.search(r"\bquarter\b|\bq[1-4]\b", q):
        return OperationDecision(
            clarification=(
                "A narrative account of a quarter needs a game and a measure. Which quarter "
                "measure should I rank instead?"
            ),
            options=(
                "fewest points scored in that quarter",
                "worst scoring margin in that quarter",
            ),
        )
    if _RUN_ASK.search(q):
        return _clarify_run(pinned_game=False)
    return OperationDecision(
        clarification=(
            "That sequence needs a pinned game, the event interval it covers (which minutes "
            "or possessions) and a measurable definition before I describe it from the "
            "archive. Which game date and which measure should I use?"
        ),
        options=(
            "largest scoring run in one game",
            "largest margin change in one game",
            "points, rebounds or assists by one player",
        ),
    )


def _clarify_sequence() -> OperationDecision:
    return OperationDecision(
        clarification=(
            "I have kept the archived game you named, but a full-game box-score total does "
            "not answer an event-level question. A sequence or cause needs matching "
            "play-by-play evidence and a measurable definition. I will not substitute the "
            "game's record for that evidence. Which supported measure should I report?"
        ),
        options=(
            "a player's points, rebounds and assists in that game",
            "the Knicks' scoring in a named quarter",
            "that game's final margin and result",
        ),
    )


def _clarify_superlative(q: str) -> OperationDecision:
    if _RUN_ASK.search(q):
        return _clarify_run(pinned_game=False)
    if re.search(r"\bquarter\b|\bq[1-4]\b", q):
        return OperationDecision(
            clarification="Which quarter measure should I rank the games by?",
            options=(
                "fewest points scored in that quarter",
                "worst scoring margin in that quarter",
            ),
        )
    if re.search(r"\bclose games?\b|\bblowouts?\b", q):
        return OperationDecision(
            clarification="Which final-margin cutoffs should define close games and blowouts?",
            options=("close: margin under 6; blowout: margin over 15",),
        )
    if re.search(r"\boffense or (?:the )?defense\b|\bstronger\b", q):
        return OperationDecision(
            clarification="Which measure should decide it?",
            options=("points scored versus points allowed per game", "average margin"),
        )
    if re.search(r"\bback[ -]to[ -]backs?\b", q):
        return OperationDecision(
            clarification=(
                "The archive stores game dates but no back-to-back flag. Which games should "
                "count as a back-to-back?"
            ),
            options=("second game of consecutive dates", "name the dates to count"),
        )
    return OperationDecision(
        clarification=(
            "Which players, teams or games should I compare, and which statistic and dates "
            "should I use?"
        ),
        options=(
            "points, rebounds, assists, steals, blocks or turnovers",
            "scoring margin or record",
        ),
    )


def _team_operation(q: str, *, has_player: bool = False) -> Operation | None:
    if "swing" in q:
        return "game_swings"
    if _STREAK_LOSS.search(q) or "losing streak" in q:
        return "longest_losing_streak"
    if _STREAK_WIN.search(q):
        return "longest_winning_streak"
    if _LARGEST_LOSS.search(q):
        return "largest_loss_margin"
    if _LARGEST_WIN.search(q):
        return "largest_win_margin"
    if _BEST_DEFENSIVE.search(q):
        return "lowest_opponent_points_game"
    if "margin" in q and re.search(r"\b(?:average|avg|mean)\b", q):
        return "average_margin"
    if "points allowed" in q or ("allow" in q and re.search(r"\bpoints?\b", q)):
        return "points_allowed"
    if re.search(r"\bhighest[ -]scoring\b", q):
        return "highest_scoring_game"
    if re.search(r"\blowest[ -]scoring\b", q):
        return "lowest_scoring_game"
    if "how many" in q and "games" in q and re.search(r"\b(?:win|wins|won)\b", q):
        return "win_count"
    if "how many" in q and "games" in q and re.search(r"\b(?:loss|losses|lose|lost)\b", q):
        return "loss_count"
    if "how many" in q and "games" in q and re.search(r"\bplay(?:ed)?\b", q):
        return "game_count"
    if re.search(r"\b(?:average|avg|per game)\b", q) and re.search(r"\b(?:points?|scor\w*)\b", q):
        return "points_average"
    if re.search(r"\b(?:total|how many)\b", q) and re.search(
        r"\b(?:points?|scor(?:e|ed|ing))\b", q
    ):
        return "points_total"
    if is_record_request(q):
        return "team_record"
    if re.search(r"\b(?:perform|performed|performing|done|doing)\b", q) and re.search(
        r"\b(?:against|versus|vs)\b", q
    ):
        return "team_record"
    if not has_player and _HOW_DID_DO.search(q) and _DO_VERB.search(q):
        return "team_record"
    return None


def classify_operation(
    question: str,
    *,
    has_player: bool,
    ambiguous_player: bool,
    periods: tuple[int, ...] = (),
    metric: str | None = None,
    performance_scope: Literal["game", "population", "unspecified"],
) -> OperationDecision:
    q = normalize_text(question.replace("–", "-").replace("—", "-"))
    pinned_game = performance_scope == "game"
    if _LIVE_ASK.search(q):
        return OperationDecision(reason=UNSUPPORTED_LIVE)
    if _EVENT_INTERVAL.search(q):
        return _clarify_sequence() if pinned_game else _clarify_narrative(q)
    stat = _player_stat(q)
    aggregation = requested_aggregation(q)
    threshold = _threshold(q)
    if threshold is not None:
        if _COUNT_ASK.search(q) or re.search(r"\bgames?\b", q):
            if has_player or ambiguous_player:
                if threshold.subject == "own_points" and (
                    stat is None or stat not in PERCENTAGE_STATS | RATIO_STATS
                ):
                    return OperationDecision(
                        operation="player_threshold",
                        threshold=threshold,
                        stat=stat,
                        aggregation=aggregation,
                    )
                return OperationDecision(
                    clarification=(
                        "A player threshold needs a counting stat. Which counting stat and "
                        "cutoff should I count?"
                    ),
                    options=("points", "rebounds", "assists", "three-pointers made"),
                )
            return OperationDecision(
                operation="score_threshold", threshold=threshold, aggregation=aggregation
            )
        return OperationDecision(reason=UNSUPPORTED_MARGIN_WITHOUT_COUNT)
    if _LEADER_ASK.search(q):
        if metric is None:
            return OperationDecision(
                clarification="Which statistic should I rank the Knicks players by?",
                options=("points", "rebounds", "assists", "steals", "blocks", "turnovers"),
            )
        if stat in PERCENTAGE_STATS:
            return OperationDecision(
                clarification=(
                    "A shooting percentage needs a minimum-attempt rule and a season or "
                    "window. Rank by total makes, or name the window to rank by percentage?"
                ),
                options=("total makes", "percentage over this archive"),
            )
        return OperationDecision(operation="player_leaderboard", aggregation=aggregation)
    if stat is not None and (has_player or ambiguous_player):
        return OperationDecision(operation="player_metric", stat=stat, aggregation=aggregation)
    if (
        _WINS.search(q)
        and _LOSSES.search(q)
        and (_SHOOTING_WORD.search(q) or re.search(r"\b(?:compare|comparison|versus|vs)\b", q))
        and not has_player
    ):
        specific = stat
        if specific is None:
            specific = (
                "margin"
                if _MARGIN_MEASURE.search(q)
                else "field_goal_percentage"
                if _SHOOTING_WORD.search(q)
                else None
            )
        return OperationDecision(operation="result_split", stat=specific, aggregation=aggregation)
    measures = _requested_measures(question)
    if measures:
        return OperationDecision(
            operation=measures[0].operation,
            measures=measures,
            stat=stat,
            aggregation=measures[0].aggregation,
        )
    if (
        has_player
        and stat is None
        and metric is None
        and aggregation is None
        and _PERFORMANCE_ASK.search(q)
    ):
        if performance_scope == "population" and not re.search(r"\bstat\s*line\b", q):
            return OperationDecision(operation="player_metric", aggregation="average")
        return OperationDecision(operation="player_game_summary")
    if (
        pinned_game
        and stat is None
        and metric is None
        and aggregation is None
        and _SEQUENCE_ASK.search(q)
    ):
        return _clarify_sequence()
    operation = _team_operation(q, has_player=has_player)
    if periods and _SCORING_WORD.search(q) and not has_player:
        return OperationDecision(operation="period_scoring", stat=stat, aggregation=aggregation)
    if operation is not None and not (has_player and operation in PLAYER_SUBJECT_OPERATIONS):
        return OperationDecision(
            operation=operation,
            stat=stat,
            aggregation=_operation_aggregation(operation, aggregation),
        )
    if has_player and operation in PLAYER_SUBJECT_OPERATIONS:
        return OperationDecision(
            operation="player_metric",
            stat=stat,
            aggregation=_operation_aggregation(operation, aggregation),
        )
    if _COMPARATIVE_ASK.search(q) and stat is None and metric is None:
        return _clarify_superlative(q)
    if pinned_game:
        return OperationDecision()
    if _NARRATIVE_ASK.search(q):
        return _clarify_narrative(q)
    if _DEFINITION_ASK.search(q):
        return _clarify_superlative(q)
    if (has_player or ambiguous_player) and (
        metric or stat or not (_WINS.search(q) or _LOSSES.search(q))
    ):
        return OperationDecision(operation="player_metric", stat=stat, aggregation=aggregation)
    if _RANKING_WORD.search(q):
        return _clarify_superlative(q)
    return OperationDecision()
