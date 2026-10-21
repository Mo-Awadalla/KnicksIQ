"""Numeric checks. Every claimed value here is compared with a SQL result."""

from decimal import Decimal

T = 0.005


def C(label, claimed, fn, quote, tol=T):
    return {"label": label, "claimed": claimed, "fn": fn, "quote": quote, "tol": tol}


def bx(f, name, game_id, field):
    return f["box"][f"{name}|{game_id}"][field]


def dates(f, opp):
    return [r["game_date"] for r in f["matchups"][opp]]


def rec(f, name):
    r = f["splits"][name]
    return f'{r["wins"]}-{r["losses"]}'


def msum(f, opp):
    return f["matchup_summary"][opp + "|all"]


def box(f, name, game_id):
    return f["box"][f"{name}|{game_id}"]


SPECS = {
    "exact_statistics-001": {
        "claims": [
            C("wins", 69, "core.all.wins", "went 69-32"),
            C("losses", 32, "core.all.losses", "went 69-32"),
            C("games", 101, "core.all.games", "across 101 games"),
        ],
        "flags": ["season_scope"],
        "note": "All-phase 69-32 across 101 games; regular season only is 53-29.",
    },
    "exact_statistics-002": {
        "claims": [
            C("points", 11750, "core.all.points", "11,750 total points"),
            C("games", 101, "core.all.games", "across 101 archived games"),
        ],
        "flags": ["season_scope"],
        "note": "All-phase 11,750; regular season only is 9,549.",
    },
    "exact_statistics-003": {
        "claims": [
            C("avg_points", 116.34, "core.all.avg_points", "averaged 116.34"),
            C("games", 101, "core.all.games", "across 101 games"),
        ],
        "flags": ["season_scope"],
        "note": "All-phase 116.34; regular season only is 116.45.",
    },
    "exact_statistics-004": {
        "claims": [
            C("avg_margin", 7.94, "core.all.avg_margin", "average margin was 7.94"),
            C("games", 101, "core.all.games", "across 101 archived games"),
        ],
        "flags": ["season_scope"],
        "note": "All-phase 7.94; regular season only is 6.33.",
    },
    "exact_statistics-005": {
        "claims": [C("home_wins", 37, "core.all.home_wins", "won 37 home games")],
        "flags": ["season_scope"],
        "note": "All-phase 37 home wins; regular season only is 30.",
    },
    "exact_statistics-006": {
        "claims": [C("away_wins", 32, "core.all.away_wins", "won 32 road games")],
        "flags": ["season_scope"],
        "note": "All-phase 32 road wins; regular season only is 23.",
    },
    "exact_statistics-007": {
        "claims": [
            C("losses", 32, "core.all.losses", "lost 32 games"),
            C("games", 101, "core.all.games", "across 101 archived games"),
        ],
        "flags": ["season_scope"],
        "note": "All-phase 32 losses; regular season only is 29.",
    },
    "exact_statistics-008": {
        "claims": [
            C("margin", 54, "extremes.biggest_win.margin", "54-point win"),
            C("points", 120, "extremes.biggest_win.pts", "120 points scored"),
        ],
        "right": "54 points is correct: 120-66 vs BKN on 2026-01-21 (game 44).",
        "flags": ["tool_artifact"],
    },
    "exact_statistics-009": {
        "claims": [C("losses_in_dumped_filter", 32, "core.all.losses", "Knicks losses: 32")],
        "required_terms": ["38"],
        "right": "Worst loss is 38 points: 80-118 at DET on 2026-02-06 (game 52).",
        "tables": ["games", "team_game_stats"],
        "note": "The dumped 0-32 / 3421 aggregate is the 32-loss subset, not the worst loss.",
    },
    "exact_statistics-010": {
        "claims": [
            C("player_points", 47, lambda f: f["extremes"]["highest_player_game"]["points"], "47 points"),
            C("next_player_points", 45, lambda f: f["extremes"]["second_highest_player_game"]["points"], "45 points"),
        ],
        "required_terms": ["146"],
        "right": "Team highest-scoring game is 146 points, 146-112 vs UTA on 2025-12-05 (game 22). The 47 is the player high, a different question.",
        "flags": ["question_drift"],
        "tables": ["games", "player_game_stats"],
        "hand": True,
        "hand_reason": "The wording is ambiguous between team and player; the benchmark draft facts use the team total, so this interpretation is hand-set.",
    },
    "date_range_last_n-001": {
        "claims": [
            C("record", "4-1", lambda f: rec(f, "last5"), "went 4-1"),
            C("points", 522, "splits.last5.points", "scored 522"),
            C("margin", 12, "splits.last5.margin", "total margin of +12"),
        ],
        "right": "4-1, 522 points, +12 over 2026-06-03 to 2026-06-13.",
    },
    "date_range_last_n-002": {
        "claims": [
            C("avg_points", 114.1, "splits.last10.avg_points", "averaged 114.1"),
            C("record", "9-1", lambda f: rec(f, "last10"), "9 wins, 1 loss"),
        ],
        "right": "114.1 ppg and 9-1 over the last 10 (2026-05-10 to 2026-06-13).",
    },
    "date_range_last_n-003": {
        "claims": [
            C("avg_points", 32.6, "player_windows.brunson_last5_avg", "averaged 32.6"),
            C("games", 5, lambda f: len(f["player_windows"]["brunson_last5"]), "last 5 observed games"),
        ],
        "right": "32.6 over his last five appearances, 2026-06-03 to 2026-06-13.",
    },
    "date_range_last_n-004": {
        "claims": [
            C("record", "7-8", lambda f: rec(f, "january"), "went 7-8"),
            C("games", 15, "splits.january.games", "across 15 games"),
            C("points", 1652, "splits.january.points", "1,652 total points"),
        ],
        "right": "7-8 in 15 games, 1,652 points, 2026-01-02 to 2026-01-30.",
    },
    "date_range_last_n-006": {
        "claims": [
            C("record", "5-0", lambda f: rec(f, "dec_away"), "5 wins, 0 losses"),
            C("games", 5, "splits.dec_away.games", "across 5 archived away games"),
        ],
        "right": "5-3 in 8 road games in December (LWWWLWWL). The 5 wins are right; the 0 losses and 5-game count are not.",
        "tables": ["games"],
    },
    "comparisons-002": {
        "claims": [
            C("towns_ppg", 19.2, lambda f: f["players"]["Karl-Anthony Towns"]["ppg"], "19.2 points", tol=0.05),
            C("towns_appearances", 94, lambda f: f["players"]["Karl-Anthony Towns"]["appearances"], "94 observed appearances"),
            C("brunson_ppg", 26.5, lambda f: f["players"]["Jalen Brunson"]["ppg"], "26.5 points", tol=0.05),
            C("brunson_appearances", 93, lambda f: f["players"]["Jalen Brunson"]["appearances"], "93 observed appearances"),
        ],
        "right": "Towns 19.2 over 94 appearances, Brunson 26.5 over 93. Correct, though the answer does not state the conclusion that Brunson scored more.",
    },
    "comparisons-008": {
        "claims": [
            C("towns_rpg", 11.6, lambda f: f["players"]["Karl-Anthony Towns"]["rpg"], "11.6", tol=0.05),
            C("towns_appearances", 94, lambda f: f["players"]["Karl-Anthony Towns"]["appearances"], "94 appearances"),
            C("hart_rpg", 7.7, lambda f: f["players"]["Josh Hart"]["rpg"], "7.7", tol=0.05),
            C("hart_appearances", 85, lambda f: f["players"]["Josh Hart"]["appearances"], "85 appearances"),
        ],
        "right": "Towns 11.6 over 94 appearances, Hart 7.7 over 85. Towns had more rebounds per appearance.",
    },
    "single_game_narrative-002": {
        "claims": [C("toronto_dates", ["2025-11-30", "2025-12-09", "2026-01-28", "2026-03-03", "2026-04-10"], lambda f: dates(f, "TOR"), "2025-11-30 ... 2026-04-10")],
        "right": "All five Toronto dates are correct; asking which game is appropriate.",
        "tables": ["games"],
        "hand": True,
        "hand_reason": "A clarification is the right behavior; the script verifies the date list.",
    },
    "single_game_narrative-007": {
        "claims": [C("boston_dates", ["2025-10-24", "2025-12-02", "2026-02-08", "2026-04-09"], lambda f: dates(f, "BOS"), "2025-10-24 ... 2026-04-09")],
        "right": "All four Boston dates are correct; asking which game is appropriate.",
        "tables": ["games"],
        "hand": True,
        "hand_reason": "Clarification among four real games; date list is checked by SQL.",
    },
    "single_game_narrative-009": {
        "claims": [
            C("atl_dates_are_real", True,
              lambda f: all(d in dates(f, "ATL") for d in ["2025-12-27", "2026-01-02", "2026-04-06", "2026-04-18", "2026-04-20", "2026-04-23", "2026-04-25", "2026-04-28"]),
              "2025-12-27 ... 2026-04-28"),
        ],
        "verdict": "CORRECT",
        "flags": ["incomplete_matchup_list"],
        "right": "All eight listed Atlanta dates are real; the ninth is 2026-04-30. 'Including' makes the list nonexhaustive, so this is a valid clarification.",
        "tables": ["games"],
        "hand": True,
        "hand_reason": "Deciding that an eight-of-nine list is acceptable is a judgment; dates are SQL-checked.",
    },
    "turning_points-002": {
        "claims": [C("toronto_dates", ["2025-11-30", "2025-12-09", "2026-01-28", "2026-03-03", "2026-04-10"], lambda f: dates(f, "TOR"), "2025-11-30 ... 2026-04-10")],
        "right": "All five Toronto dates are correct; asking which game is appropriate.",
        "tables": ["games"],
        "hand": True,
        "hand_reason": "Clarification among real games; date list is SQL-checked.",
    },
    "turning_points-004": {
        "claims": [C("chicago_dates", ["2025-10-31", "2025-11-02", "2026-02-22", "2026-04-03"], lambda f: dates(f, "CHI"), "2025-10-31 ... 2026-04-03")],
        "right": "All four Chicago dates are correct; asking which game is appropriate.",
        "tables": ["games"],
        "hand": True,
        "hand_reason": "Clarification among real games; date list is SQL-checked.",
    },
    "turning_points-006": {
        "claims": [C("boston_dates", ["2025-10-24", "2025-12-02", "2026-02-08", "2026-04-09"], lambda f: dates(f, "BOS"), "2025-10-24 ... 2026-04-09")],
        "right": "All four Boston dates are correct; asking which game and defining 'drought' is appropriate.",
        "tables": ["games"],
        "hand": True,
        "hand_reason": "Clarification plus ambiguity handling; date list is SQL-checked.",
    },
    "turning_points-010": {
        "claims": [
            C("atl_dates_are_real", True,
              lambda f: all(d in dates(f, "ATL") for d in ["2025-12-27", "2026-01-02", "2026-04-06", "2026-04-18", "2026-04-20", "2026-04-23", "2026-04-25", "2026-04-28"]),
              "2025-12-27 ... 2026-04-28"),
        ],
        "verdict": "CORRECT",
        "flags": ["incomplete_matchup_list"],
        "right": "Eight of nine Atlanta dates are listed; 2026-04-30 is missing. 'Any of these' is not exhaustive, so this remains a usable clarification.",
        "tables": ["games"],
        "hand": True,
        "hand_reason": "Judging an eight-of-nine list acceptable is a judgment; dates are SQL-checked.",
    },
    "aliases_typos-001": {
        "claims": [
            C("record", "3-1", lambda f: f'{msum(f,"BOS")["wins"]}-{msum(f,"BOS")["losses"]}', "went 3-1"),
            C("games", 4, lambda f: msum(f, "BOS")["games"], "across 4 games"),
            C("points", 445, lambda f: msum(f, "BOS")["points"], "445 total points"),
        ],
        "right": "3-1 in four regular-season games vs BOS, 445 points. Correct.",
    },
    "aliases_typos-002": {
        "claims": [
            C("points", 35, lambda f: bx(f, "Mikal Bridges", 20, "points"), "35 points"),
            C("rebounds", 6, lambda f: bx(f, "Mikal Bridges", 20, "rebounds"), "6 rebounds"),
            C("assists", 3, lambda f: bx(f, "Mikal Bridges", 20, "assists"), "3 assists"),
            C("turnovers", 0, lambda f: bx(f, "Mikal Bridges", 20, "turnovers"), "0 turnovers"),
            C("threes", 8, lambda f: bx(f, "Mikal Bridges", 20, "three_pointers_made"), "8 three-pointers"),
            C("minutes", 33.6, lambda f: bx(f, "Mikal Bridges", 20, "minutes"), "33.6 minutes"),
            C("score", "123-117", lambda f: f'{box(f,"Mikal Bridges",20)["home_score"]}-{box(f,"Mikal Bridges",20)["away_score"]}', "123-117"),
        ],
        "right": "All box-score values and the 123-117 Boston score are correct.",
    },
    "aliases_typos-004": {
        "claims": [
            C("points", 21, lambda f: bx(f, "Karl-Anthony Towns", 62, "points"), "21 points"),
            C("rebounds", 12, lambda f: bx(f, "Karl-Anthony Towns", 62, "rebounds"), "12 rebounds"),
            C("assists", 6, lambda f: bx(f, "Karl-Anthony Towns", 62, "assists"), "6 assists"),
            C("turnovers", 3, lambda f: bx(f, "Karl-Anthony Towns", 62, "turnovers"), "3 turnovers"),
            C("minutes", 29, lambda f: bx(f, "Karl-Anthony Towns", 62, "minutes"), "about 29 minutes", tol=0.5),
            C("score", "111-95", lambda f: f'{box(f,"Karl-Anthony Towns",62)["away_score"]}-{box(f,"Karl-Anthony Towns",62)["home_score"]}', "111-95"),
            C("appearances_vs_tor", 1, lambda f: f["player_matchups"]["kat_vs_tor_avg"]["appearances"], "a single observed appearance"),
        ],
        "right": "The 2026-03-03 line is correct, but Towns has five appearances vs TOR, not one: 17.4 ppg, 13.6 rpg, 3.2 apg over five games.",
        "tables": ["player_game_stats", "games"],
    },
    "aliases_typos-006": {
        "claims": [
            C("points", 39, lambda f: bx(f, "Jalen Brunson", 87, "points"), "39 points"),
            C("rebounds", 3, lambda f: bx(f, "Jalen Brunson", 87, "rebounds"), "3 rebounds"),
            C("assists", 8, lambda f: bx(f, "Jalen Brunson", 87, "assists"), "8 assists"),
            C("turnovers", 1, lambda f: bx(f, "Jalen Brunson", 87, "turnovers"), "1 turnover"),
            C("minutes", 34.7, lambda f: bx(f, "Jalen Brunson", 87, "minutes"), "34.7 minutes", tol=0.05),
            C("plus_minus", 23, lambda f: bx(f, "Jalen Brunson", 87, "plus_minus"), "+23"),
            C("score", "126-97", lambda f: f'{box(f,"Jalen Brunson",87)["home_score"]}-{box(f,"Jalen Brunson",87)["away_score"]}', "126-97"),
        ],
        "required_terms": ["6-3"],
        "right": "The Knicks went 6-3 vs ATL (2-1 regular season, 4-2 playoffs). The answer gives only one player's line from one game, so it does not answer 'how did they do'.",
        "tables": ["games", "player_game_stats"],
    },
    "aliases_typos-009": {
        "claims": [
            C("og_ppg", 11.5, lambda f: f["player_matchups"]["og_vs_bos_avg"]["ppg"], "averaged 11.5"),
            C("og_appearances", 2, lambda f: f["player_matchups"]["og_vs_bos_avg"]["appearances"], "2 observed appearances"),
            C("rows_missing_claim", True,
              lambda f: any(r["game_id"] in (20, 53) and r["nyk_rows"] < 8
                            for r in f["player_matchups"]["nyk_rows_by_game"]),
              "player rows are missing for two of the four archived games (game IDs 20 and 53)"),
        ],
        "right": "OG averaged 11.5 over two appearances, but no player rows are missing: game 20 has 12 NYK rows and game 53 has 14. Anunoby simply did not appear in those two games.",
        "tables": ["player_game_stats", "games"],
    },
    "aliases_typos-010": {
        "claims": [
            C("wins", 69, "core.all.wins", "Knicks wins: 69"),
            C("losses", 32, "core.all.losses", "Knicks losses: 32"),
            C("points", 11750, "core.all.points", "Knicks points: 11750"),
        ],
        "required_terms": ["19"],
        "right": "Worst collapse by blown lead is 19 points on 2025-12-31 at SAS (134-132, game 33); the worst loss by final margin is 38 at DET on 2026-02-06. The dumped 69-32 / 11750 totals are true but answer neither.",
        "tables": ["games", "game_events"],
    },
    "unsupported-007": {
        "claims": [
            C("points", 47, lambda f: bx(f, "Jalen Brunson", 28, "points"), "47 points"),
            C("latest_date", "2025-12-21", "extremes.latest_game_date", "latest dated game is 2025-12-21"),
        ],
        "right": "The decline is appropriate, but the latest dated game is 2026-06-13, not 2025-12-21.",
        "flags": ["stale_recency"],
        "tables": ["games"],
        "note": "The response correctly declines 'yesterday' but states a false archive recency.",
    },
    "unsupported-009": {
        "claims": [C("lakers_dates", ["2026-02-01", "2026-03-08"], lambda f: dates(f, "LAL"), "2026-02-01 ... 2026-03-08")],
        "verdict": "CORRECT",
        "flags": ["benchmark_label_wrong"],
        "right": "There are two Lakers games, so asking which one is correct. The benchmark label says not answerable; the archive has both games.",
        "tables": ["games"],
        "hand": True,
        "hand_reason": "The benchmark label is wrong; deciding that a clarification is correct is semantic.",
    },
    "unsupported-010": {
        "claims": [C("boston_dates", ["2025-10-24", "2025-12-02", "2026-02-08", "2026-04-09"], lambda f: dates(f, "BOS"), "2025-10-24 ... 2026-04-09")],
        "verdict": "CORRECT",
        "flags": ["benchmark_label_wrong"],
        "right": "There are four Celtics games, so asking which one is correct. The benchmark label says not answerable; the archive has all four.",
        "tables": ["games"],
        "hand": True,
        "hand_reason": "The benchmark label is wrong; deciding that a clarification is correct is semantic.",
    },
    "comparisons-007": {
        "claims": [
            C("games", 4, lambda f: msum(f, "BOS")["games"], "four Knicks games against Boston"),
            C("record", "3-1", lambda f: f'{msum(f,"BOS")["wins"]}-{msum(f,"BOS")["losses"]}', "went 3-1"),
        ],
        "verdict": "UNSUPPORTED_CLAIM",
        "findings": [{
            "type": "UNSUPPORTED_CLAIM",
            "quote": "I don't have per-game scoring or margin details for each of those games in the current evidence",
            "detail": "False. games has final scores and team_game_stats has per-game margins for all four Boston games.",
            "evidence": "games vs BOS: 105-95, 117-123, 111-89, 112-106; margins +10, -6, +22, +6",
        }],
        "right": "Four games and 3-1 are correct, but the archive does have per-game scores and margins. The false limitation blocks the comparison.",
        "tables": ["games", "team_game_stats"],
        "hand": True,
        "hand_reason": "The primary record is correct; the coverage limitation is the defect.",
    },
    "turning_points-003": {
        "claims": [
            C("wins_vs_atl", 6, lambda f: msum(f, "ATL")["wins"], "Knicks wins: 6"),
            C("losses_vs_atl", 3, lambda f: msum(f, "ATL")["losses"], "Knicks losses: 3"),
            C("points_vs_atl", 1042, lambda f: msum(f, "ATL")["points"], "Knicks points: 1042"),
        ],
        "required_terms": ["14"],
        "right": "The 6-3 / 1,042 aggregates are true for the nine Atlanta games, but they do not answer when a collapse happened. The largest lead lost was 14 points on 2026-04-20 (106-107); the largest deficit was 26 on 2026-01-02.",
        "tables": ["games", "game_events"],
    },
}
