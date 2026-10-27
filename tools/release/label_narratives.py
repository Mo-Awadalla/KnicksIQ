"Scope and evidence requirements for narrative, follow-up, and unsupported cases."

from __future__ import annotations


def review_single_game_narrative(review, n):
    review.route = "retrieval_rag"
    opponents = {
        1: "BOS",
        2: "TOR",
        3: "ATL",
        4: "CHI",
        5: "CHA",
        7: "BOS",
        8: "TOR",
        9: "ATL",
        10: "CHI",
        12: "CHA",
        13: "TOR",
        14: "BOS",
        16: "ATL",
        17: "CHI",
        19: "TOR",
        20: "BOS",
    }
    if n in opponents:
        selected = review.canonical.games_against(opponents[n])
        if n == 20:
            selected = [x for x in selected if review.canonical.margin(x) < 0]
        if len(selected) != 1:
            review.clarify(
                (
                    "No unique game/date is identified. Request a date and avoid treating a "
                    "narrative premise as proven."
                ),
                selected,
            )
        else:
            review.scorelines(selected)
            review.clarify(
                "Game identity is unique, but causal/decisive premise needs "
                "qualification. Use corrected report interval as a descriptive example, "
                "not causal proof."
            )
    elif n == 6:
        selected = review.canonical.extreme(lambda x: abs(review.canonical.margin(x)), False)
        if len(selected) != 1:
            review.clarify(
                "Multiple games tie for smallest final margin; ask which date.", selected
            )
        else:
            review.scorelines(selected)
    elif n == 11:
        selected = review.canonical.extreme(review.canonical.margin)
        review.player_stat("Towns", "points", mode="total", games=selected)
        review.player_stat("Towns", "rebounds", mode="total", games=selected)
        review.player_stat("Towns", "assists", mode="total", games=selected)
        review.scorelines(selected)
    elif n == 15:
        selected = review.canonical.extreme(review.canonical.allowed, False)
        review.scorelines(selected)
        review.notes.append(
            "Best defensive game defined as fewest opponent points, not causal tactical quality."
        )
    elif n == 18:
        rows = [
            r
            for r in review.canonical.data["period_scores"]
            if r["team_id"] == "NYK" and r["period"] == 3
        ]
        low = min(r["points"] for r in rows)
        review.fact(
            "fewest_third_quarter_points",
            low,
            [r for r in rows if r["points"] == low],
            "period_scores",
        )
        review.clarify(
            "Worst third quarter may mean fewest scored or worst net margin. Specify "
            "the metric before calling one worst."
        )


def review_turning_points(review, n):
    opponents = {1: "BOS", 2: "TOR", 3: "ATL", 4: "CHI", 6: "BOS", 8: "CHA", 9: "TOR", 10: "ATL"}
    if n in opponents:
        selected = review.canonical.games_against(opponents[n])
        if n == 6:
            selected = [x for x in selected if review.canonical.margin(x) < 0]
        review.clarify(
            (
                "Specify the game and scoring-run definition. A selected bounded "
                "scoreboard interval does not prove a causal turning point, collapse or "
                "drought that cost the game."
            ),
            selected,
        )
    else:
        review.clarify(
            "Specify comeback/run boundaries and whether biggest means unanswered "
            "points, net margin or duration. Corrected report intervals use an "
            "explicit three-minute bound and cannot establish an unrestricted season "
            "superlative."
        )


def review_follow_ups(review, n):
    review.clarify(
        (
            "Supplied conversation does not pin a game, event interval or valid "
            "evidence. The assistant's asserted decisive Boston run is not canonical "
            "proof. Ask for a game/date or cited interval."
        ),
        review.canonical.games_against("BOS"),
    )
    if n == 3:
        review.notes.append(
            "Exact on-court lineup needs validated substitution reconstruction; "
            "player box-score participation is not lineup evidence."
        )


def review_aliases_typos(review, n):
    if n in (1, 6):
        selected = review.canonical.games_against("BOS" if n == 1 else "ATL")
        review.record(selected, "BOS" if n == 1 else "ATL")
        review.notes.append(
            "Alias resolves an aggregate opponent record; original retrieval_rag "
            "route recommendation should be table_rag."
        )
    elif n in (4, 8, 9):
        selected = review.canonical.games_against("BOS" if n == 9 else "TOR")
        review.player_stat({4: "Towns", 8: "Bridges", 9: "Anunoby"}[n], "points", games=selected)
        review.notes.append(
            "Offer canonical scoring average for all games against this opponent, "
            "explicitly name the aggregate scope; subjective played-well language is "
            "not a factual label."
        )
    elif n in (2, 7):
        review.clarify(
            ("Typo/alias is understandable, but multiple matching opponent games require a date."),
            review.canonical.games_against("BOS" if n == 2 else "CHI"),
        )
    elif n == 3:
        review.clarify("JB resolves to Jalen Brunson, but 'that game' has no provided context.")
    else:
        review.clarify(
            "Typo is understandable; define scoring run or collapse before choosing "
            "a season-wide superlative."
        )


def review_unsupported(review, n):
    if n in (1, 2, 3, 4, 5, 6, 7, 8, 15):
        review.refuse(
            "Outside the immutable 2025-26 archive: no live, future, injury, trade, "
            "betting or out-of-range evidence. Do not invent current facts."
        )
    elif n == 9:
        review.clarify(
            (
                "Lakers is an archived opponent with two games. This is ambiguous, not "
                "unsupported solely because it names Lakers."
            ),
            review.canonical.games_against("LAL"),
        )
    elif n == 10:
        review.clarify(
            (
                "No prior game selection exists in the supplied context. List the "
                "archived Boston dates and ask which."
            ),
            review.canonical.games_against("BOS"),
        )
    else:
        review.clarify(
            "Missing game, player, time period or evaluation metric. Ask for the "
            "intended scope; generic language alone does not prove an out-of-archive "
            "request."
        )
