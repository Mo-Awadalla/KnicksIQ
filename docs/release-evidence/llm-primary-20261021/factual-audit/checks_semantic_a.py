"""Semantic checks: splits and comparisons where the response declines."""

from checks_numeric import C


def S(verdict, right, tables, score, note="", flags=None, findings=None, hand_reason=""):
    return {
        "verdict": verdict,
        "right": right,
        "tables": tables,
        "data_score": score,
        "note": note,
        "flags": flags or [],
        "findings": findings or [],
        "hand": True,
        "hand_reason": hand_reason or "Verdict is a judgment about whether the question was answered or appropriately declined.",
    }


def F(quote, detail, evidence, kind="UNSUPPORTED_CLAIM"):
    return {"type": kind, "quote": quote, "detail": detail, "evidence": evidence}


SPECS = {
    "date_range_last_n-005": S(
        "DECLINE_MISSED_ANSWER",
        "18-9 in 27 regular-season games after the break (2026-02-19 to 2026-04-12); 34-12 including playoffs.",
        ["games"],
        lambda f: f["splits"]["post_asb_regular"]["games"],
        note="All questions in the set are about the Knicks, so asking 'which team' is not a real ambiguity. The All-Star break is 2026-02-12 to 2026-02-18 in this schedule.",
    ),
    "date_range_last_n-007": S(
        "DECLINE_MISSED_ANSWER",
        "9.75 average margin over the last 8 (78 total margin, 7-1, 110.25 ppg).",
        ["games"],
        lambda f: f["splits"]["last8"]["games"],
        note="The response correctly quotes 110.25 ppg, then says no margin value exists. Margin is games.home_score - games.away_score.",
        findings=[F("the available evidence includes ... points per game (110.25), but no margin value", "Margin is derivable for every game in games; total margin over the eight games is 78.", "last8: 8 games, 78 margin, 9.75 avg")],
    ),
    "date_range_last_n-008": S(
        "DECLINE_MISSED_ANSWER",
        "Jalen Brunson led the Knicks over the last 3 games with 113 points (37.7 ppg).",
        ["player_game_stats"],
        lambda f: f["coverage"]["last3_player_rows"],
        note="The last three games are 2026-06-08, 2026-06-10, 2026-06-13. Asking 'which player' inverts the question, which asks who led the team.",
    ),
    "date_range_last_n-009": S(
        "DECLINE_MISSED_ANSWER",
        "9 games between 2026-03-01 and 2026-03-15.",
        ["games"],
        lambda f: f["splits"]["mar1_15"]["games"],
        note="The context is the Knicks; 'they' does not need clarification.",
    ),
    "date_range_last_n-010": S(
        "DECLINE_MISSED_ANSWER",
        "7-3 in the first 10 games, with 1,218 points and +91 margin (all regular season).",
        ["games"],
        lambda f: f["splits"]["first10"]["games"],
        note="The first 10 archived games are all regular season, so the regular/playoff clarification is unnecessary.",
    ),
    "comparisons-001": S(
        "DECLINE_MISSED_ANSWER",
        "Home 118.20 ppg over 49 games; road 114.58 ppg over 52 games. The home offense was 3.62 ppg better.",
        ["games", "team_game_stats"],
        lambda f: f["coverage"]["team_rows"] + f["core"]["all"]["games"],
        note="The response says the evidence covers only 48 home games and no road games. The restore has 49 home and 52 road games.",
        findings=[
            F("the available evidence covers only Knicks home games (48 games in scope), with no road-game data retrieved", "Both the count and the coverage claim are false: 49 home games and 52 road games are present.", "home: 49 games, 118.20 ppg; away: 52 games, 114.58 ppg"),
            F("48 games in scope", "The home-game count is 49, not 48.", "home_games=49, away_games=52", kind="INCORRECT"),
        ],
    ),
    "comparisons-003": S(
        "DECLINE_MISSED_ANSWER",
        "3-1 vs BOS with a +32 point differential; 5-0 vs TOR with +98. The Toronto series was better.",
        ["games", "team_game_stats"],
        lambda f: sum(r["games"] for r in f["coverage"]["by_opponent"] if r["opp"] in ("BOS", "TOR")),
        note="Opponent splits are directly available from games and team_game_stats.",
        findings=[F("does not include Knicks results broken out by opponent Boston or Toronto", "False: four BOS games and five TOR games are in the restore with scores and team box totals.", "BOS 4 games 3-1 +32; TOR 5 games 5-0 +98")],
    ),
    "comparisons-004": S(
        "DECLINE_MISSED_ANSWER",
        "First 10: 7-3, 121.8 ppg, +91. Last 10: 9-1, 114.1 ppg, +119. The last 10 had the better record and margin; the first 10 scored more.",
        ["games"],
        lambda f: 20,
        note="Both windows are unambiguous in the archive; no clarification is needed.",
    ),
    "comparisons-005": S(
        "DECLINE_MISSED_ANSWER",
        "11.97 turnovers per win (69 games) vs 14.28 per loss (32 games); the Knicks turned it over less in wins.",
        ["team_game_stats", "games"],
        lambda f: f["coverage"]["team_rows"],
        note="Win/loss splits are available from games joined to team_game_stats.",
        findings=[F("no loss count or average turnover figures for wins versus losses were returned", "False: the restore has 32 losses and team_game_stats.turnovers for every game.", "W: 11.97 TOV over 69; L: 14.28 over 32")],
    ),
    "comparisons-006": S(
        "DECLINE_MISSED_ANSWER",
        "Bench averaged 32.12 ppg at home vs 29.88 on the road, so the bench was more productive at home.",
        ["player_game_stats", "games"],
        lambda f: f["coverage"]["nyk_player_rows"],
        note="The starter flag identifies bench players; every game has NYK player rows (minimum 12).",
        findings=[F("the retrieved data covers only home games and identifies a single player appearance", "False: 49 home and 52 road games are present, and player_game_stats has 1,384 NYK rows with a starter flag.", "bench home 32.12 ppg; away 29.88 ppg")],
    ),
    "comparisons-009": S(
        "DECLINE_MISSED_ANSWER",
        "Third quarter 29.02 ppg vs fourth quarter 27.89 ppg across 101 games.",
        ["period_scores"],
        lambda f: f["coverage"]["period_rows"],
        note="period_scores has four quarters for every game, plus overtime periods.",
        findings=[F("quarter-by-quarter splits aren't in the data I can query", "False: period_scores covers all 101 games, 816 rows including OT.", "Q3 2,931 points / 101 = 29.02; Q4 2,817 / 101 = 27.89")],
    ),
    "comparisons-010": S(
        "DECLINE_MISSED_ANSWER",
        "Field-goal percentage was 49.75 in wins (69 games) and 44.16 in losses (32 games); the Knicks shot better in wins.",
        ["team_game_stats", "games"],
        lambda f: f["coverage"]["team_rows"],
        note="The response says the archive covers only wins. It has all 32 losses, and shooting splits are available.",
        flags=["internal_jargon"],
        findings=[F("the archive here covers only Knicks wins (game_result = W), so there are no loss games to compare shooting against", "False: 32 losses are present. team_game_stats has FGM/FGA for every game.", "W FG% 49.75 (69); L FG% 44.16 (32)")],
    ),
}
