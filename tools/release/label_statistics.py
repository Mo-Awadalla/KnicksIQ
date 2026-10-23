"""Independent arithmetic for exact statistics, date scopes, and comparisons."""

from __future__ import annotations

from datetime import date

from label_canonical import ALL_STAR_END


def review_exact_statistics(review, n):
    if n == 1:
        review.record(review.canonical.games)
    elif n == 2:
        review.fact(
            "points",
            sum(review.canonical.own(x) for x in review.canonical.games),
            review.canonical.games,
        )
    elif n in (3, 4, 25):
        review.average(
            review.canonical.games,
            {3: review.canonical.own, 4: review.canonical.margin, 25: review.canonical.allowed}[n],
            {3: "points_per_game", 4: "average_margin", 25: "points_allowed_per_game"}[n],
        )
    elif n in (5, 6):
        selected = [x for x in review.canonical.games if (x["home_team_id"] == "NYK") == (n == 5)]
        review.fact(
            "wins",
            review.canonical.record(selected)["wins"],
            selected,
            scope="home" if n == 5 else "away",
        )
    elif n == 7:
        review.fact(
            "losses",
            review.canonical.record(review.canonical.games)["losses"],
            review.canonical.games,
        )
    elif n in (8, 9, 10, 11):
        selected = review.canonical.extreme(
            review.canonical.margin if n in (8, 9) else review.canonical.own, n in (8, 10)
        )
        review.scorelines(selected)
        if n in (8, 9):
            review.fact("margin", review.canonical.margin(selected[0]), selected)
    elif n in (12, 13):
        selected = [
            x
            for x in review.canonical.games
            if (review.canonical.own(x) >= 120 if n == 12 else review.canonical.allowed(x) < 100)
        ]
        review.fact("game_count", len(selected), selected)
    elif n in (14, 15, 16, 17, 21, 22, 23):
        options = {
            14: ("Brunson", "points", "average"),
            15: ("Brunson", "points", "total"),
            16: ("Towns", "rebounds", "average"),
            17: ("Towns", "points", "double_doubles"),
            21: ("Bridges", "three_pointers_made", "percentage"),
            22: ("Hart", "starter", "starts"),
            23: ("Anunoby", "points", "average"),
        }
        review.player_stat(*options[n])
    elif n in (18, 19, 20):
        review.leader({18: "assists", 19: "rebounds", 20: "steals"}[n], review.canonical.games)
    elif n == 24:
        selected = review.canonical.games_against("BOS")
        review.record(selected, "BOS")


def review_date_range_last_n(review, n):
    if n in (1, 10, 13):
        selected = (
            review.canonical.games[-5:]
            if n == 1
            else review.canonical.games[:10]
            if n == 10
            else [x for x in review.canonical.games if x["season_type"] == "regular"][-15:]
        )
        review.record(selected)
    elif n in (2, 7, 12):
        selected = review.canonical.games[-{2: 10, 7: 8, 12: 5}[n] :]
        review.average(
            selected,
            {2: review.canonical.own, 7: review.canonical.margin, 12: review.canonical.allowed}[n],
            {2: "points_per_game", 7: "average_margin", 12: "points_allowed_per_game"}[n],
        )
    elif n in (3, 11):
        review.player_stat(
            "Brunson" if n == 3 else "Towns",
            "points",
            last=5 if n == 3 else 7,
            scope="last appearances",
        )
    elif n == 4:
        selected = review.canonical.month(1)
        review.record(selected, "January 2026")
    elif n == 5:
        selected = [x for x in review.canonical.games if x["game_date"] > ALL_STAR_END]
        review.record(selected, "after February 15, 2026 (including postseason)")
    elif n == 6:
        selected = [x for x in review.canonical.month(12) if x["away_team_id"] == "NYK"]
        review.fact(
            "wins", review.canonical.record(selected)["wins"], selected, scope="December road games"
        )
    elif n == 8:
        selected = review.canonical.games[-3:]
        review.leader("points", selected)
    elif n == 9:
        selected = [
            x for x in review.canonical.games if "2026-03-01" <= x["game_date"] <= "2026-03-15"
        ]
        review.fact("game_count", len(selected), selected)
    elif n == 14:
        pairs = [
            (a, b)
            for a, b in zip(review.canonical.games, review.canonical.games[1:], strict=False)
            if (date.fromisoformat(b["game_date"]) - date.fromisoformat(a["game_date"])).days == 1
            and b["game_date"].startswith("2026-02")
        ]
        review.fact(
            "second_night_wins",
            sum((review.canonical.margin(b) > 0 for _, b in pairs)),
            [b for _, b in pairs],
        )
        review.fact(
            "both_games_won",
            sum(
                (
                    review.canonical.margin(a) > 0 and review.canonical.margin(b) > 0
                    for a, b in pairs
                )
            ),
            [x for pair in pairs for x in pair],
        )
        review.clarify(
            "Back-to-back wins may mean winning the second night or sweeping both "
            "games. Both canonical counts supplied; ask which definition is intended."
        )
    elif n == 15:
        review.record(review.canonical.month(1), "January 2026")
        review.record(review.canonical.month(2), "February 2026")


def review_comparisons(review, n):
    if n == 1:
        for home in (True, False):
            selected = [x for x in review.canonical.games if (x["home_team_id"] == "NYK") == home]
            review.average(
                selected, review.canonical.own, "points_per_game", "home" if home else "away"
            )
    elif n == 2:
        for name in ("Brunson", "Towns"):
            review.player_stat(name, "points")
    elif n == 3:
        for team in ("BOS", "TOR"):
            review.record(review.canonical.games_against(team), team)
            review.average(
                review.canonical.games_against(team),
                review.canonical.margin,
                "average_margin",
                team,
            )
        review.notes.append(
            "Compare record/win percentage and scoring margin, not subjective play quality."
        )
    elif n == 4:
        review.record(review.canonical.games[:10], "first 10 games")
        review.record(review.canonical.games[-10:], "last 10 games")
    elif n in (5, 10):
        for win in (True, False):
            selected = [
                x for x in review.canonical.games if (review.canonical.margin(x) > 0) == win
            ]
            ids = {x["nba_game_id"] for x in selected}
            rows = [
                r
                for r in review.canonical.data["team_game_stats"]
                if r["nba_game_id"] in ids and r["team_id"] == "NYK"
            ]
            value = (
                round(sum(r["turnovers"] for r in rows) / len(rows), 4)
                if n == 5
                else round(
                    sum(r["field_goals_made"] for r in rows)
                    / sum(r["field_goals_attempted"] for r in rows)
                    * 100,
                    4,
                )
            )
            review.fact(
                "turnovers_per_game" if n == 5 else "field_goal_percentage",
                value,
                rows,
                "team_game_stats",
                "wins" if win else "losses",
            )
    elif n == 6:
        for home in (True, False):
            selected = [x for x in review.canonical.games if (x["home_team_id"] == "NYK") == home]
            ids = {x["nba_game_id"] for x in selected}
            rows = [
                r
                for r in review.canonical.data["player_game_stats"]
                if r["nba_game_id"] in ids and r["team_id"] == "NYK" and (not r["starter"])
            ]
            review.fact(
                "bench_points_per_team_game",
                round(sum(r["points"] for r in rows) / len(selected), 4),
                rows,
                "player_game_stats",
                "home" if home else "away",
            )
        review.notes.append(
            "Bench means canonical starter=false rows; productivity defined "
            "explicitly as points per team game."
        )
    elif n == 7:
        review.clarify(
            f"Archive contains {len(review.canonical.games_against('BOS'))} Boston games, not two. "
            "Request the intended dates or compare all four explicitly.",
            review.canonical.games_against("BOS"),
        )
    elif n == 8:
        review.player_stat("Towns", "rebounds")
        review.player_stat("Hart", "rebounds")
    elif n == 9:
        for period in (3, 4):
            rows = [
                r
                for r in review.canonical.data["period_scores"]
                if r["team_id"] == "NYK" and r["period"] == period
            ]
            review.fact(
                "period_points_per_game",
                round(sum(r["points"] for r in rows) / len(review.canonical.games), 4),
                rows,
                "period_scores",
                f"quarter {period}",
            )
    elif n == 11:
        review.player_stat(
            "Bridges",
            "points",
            games=[x for x in review.canonical.games if x["game_date"] <= ALL_STAR_END],
            scope="before All-Star break",
        )
        review.player_stat(
            "Bridges",
            "points",
            games=[x for x in review.canonical.games if x["game_date"] > ALL_STAR_END],
            scope="after All-Star break including postseason",
        )
    elif n in (12, 13):
        review.clarify(
            (
                "Define strength against a league benchmark or rating; archive points "
                "alone do not establish relative offense versus defense strength."
            )
            if n == 12
            else (
                "Define close-game and blowout margin thresholds before comparing; no "
                "threshold is stated in the question."
            )
        )
    elif n == 14:
        for conf in ("East", "West"):
            selected = [
                x
                for x in review.canonical.games
                if review.canonical.conferences[review.canonical.opponent(x)] == conf
            ]
            review.record(selected, conf)
            review.average(selected, review.canonical.margin, "average_margin", conf)
    elif n == 15:
        review.player_stat("Brunson", "points", last=5, scope="last 5 appearances")
        review.player_stat("Brunson", "points", scope="season appearances")
