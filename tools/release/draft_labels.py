"""Independently review all 120 fixed questions against a pinned canonical archive.

Produces proposed labels and explicit disagreements, never owner-approved gold.
Does not import the analyst, retrieval pipeline, or evaluation response output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "release-artifacts/2025-26/release-corrected-unreviewed.json"
QUESTIONS = ROOT / "apps/api/app/evaluation/questions.jsonl"
OUTPUT = ROOT / "docs/release-evidence/evaluation-label-review-20260907"
ALL_STAR_END = "2026-02-15"
ALL_STAR_SOURCE = "https://www.nba.com/allstar/2026/"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Canonical:
    def __init__(self, payload):
        self.data = payload["data"]
        self.games = sorted(self.data["games"], key=lambda g: (g["game_date"], g["nba_game_id"]))
        self.by_id = {g["nba_game_id"]: g for g in self.games}
        self.names = {p["nba_player_id"]: p["full_name"] for p in self.data["players"]}
        self.conferences = {t["id"]: t["conference"] for t in self.data["teams"]}

    def own(self, game):
        return game["home_score"] if game["home_team_id"] == "NYK" else game["away_score"]

    def allowed(self, game):
        return game["away_score"] if game["home_team_id"] == "NYK" else game["home_score"]

    def opponent(self, game):
        return game["away_team_id"] if game["home_team_id"] == "NYK" else game["home_team_id"]

    def games_against(self, team):
        return [g for g in self.games if self.opponent(g) == team]

    def month(self, number):
        return [g for g in self.games if int(g["game_date"][5:7]) == number]

    def margin(self, game):
        return self.own(game) - self.allowed(game)

    def record(self, games):
        wins = sum(self.margin(g) > 0 for g in games)
        return {"games": len(games), "wins": wins, "losses": len(games) - wins}

    def player(self, name, games=None, last=None):
        ids = {g["nba_game_id"] for g in (self.games if games is None else games)}
        rows = [
            r
            for r in self.data["player_game_stats"]
            if r["nba_game_id"] in ids
            and r["team_id"] == "NYK"
            and name.lower() in self.names[r["nba_player_id"]].lower()
            and float(r.get("minutes") or 0) > 0
        ]
        rows.sort(key=lambda r: (self.by_id[r["nba_game_id"]]["game_date"], r["nba_game_id"]))
        return rows[-last:] if last else rows

    def evidence(self, rows, collection):
        keys = {
            "games": "game",
            "player_game_stats": "box",
            "team_game_stats": "team_box",
            "period_scores": "period",
        }
        out = []
        for r in rows:
            suffix = ""
            if collection == "player_game_stats":
                suffix = f":{r['nba_player_id']}"
            elif collection == "team_game_stats":
                suffix = f":{r['team_id']}"
            elif collection == "period_scores":
                suffix = f":{r['team_id']}:{r['period']}"
            out.append(
                {
                    "canonical_id": f"{keys[collection]}:{r['nba_game_id']}{suffix}",
                    "collection": collection,
                    "row_sha256": digest(r),
                }
            )
        return out

    def extreme(self, key, maximum=True):
        value = (max if maximum else min)(key(g) for g in self.games)
        return [g for g in self.games if key(g) == value]


def review_cases(payload, cases):
    c = Canonical(payload)
    g = c.games
    common = {
        "season_scope": "2025-26 regular season and postseason unless explicitly restricted",
        "player_rate_denominator": (
            "appearances with minutes > 0; last N player games means last N appearances"
        ),
        "all_star_boundary": {"date_exclusive": ALL_STAR_END, "source": ALL_STAR_SOURCE},
        "no_api_outputs_used": True,
        "owner_approval": None,
    }

    def review_case(case):
        cat, number = case["id"].rsplit("-", 1)
        n = int(number)
        facts, evidence, notes = [], [], []
        disposition = "answer"
        route = "table_rag"
        selected = g

        def fact(metric, value, rows, collection="games", scope=None):
            refs = c.evidence(rows, collection)
            facts.append(
                {
                    "metric": metric,
                    "value": value,
                    "scope": scope or "archive",
                    "canonical_evidence_ids": [r["canonical_id"] for r in refs],
                }
            )
            evidence.extend(refs)

        def record(rows, scope="archive"):
            for metric, value in c.record(rows).items():
                fact(metric, value, rows, scope=scope)

        def average(rows, score_fn, metric, scope="archive"):
            numerator = sum(score_fn(row) for row in rows)
            value = round(numerator / len(rows), 4) if rows else None
            fact(metric, value, rows, scope=scope)
            facts[-1]["numerator"] = numerator
            facts[-1]["denominator"] = len(rows)

        def player_stat(name, metric, mode="average", games=None, last=None, scope=None):
            rows = c.player(name, games, last)
            if not rows:
                raise ValueError(f"No appearances for {name}")
            values = [r[metric] for r in rows]
            value = sum(values) if mode == "total" else round(sum(values) / len(values), 4)
            if mode == "double_doubles":
                value = sum(
                    sum(r[k] >= 10 for k in ("points", "rebounds", "assists", "steals", "blocks"))
                    >= 2
                    for r in rows
                )
            elif mode == "starts":
                value = sum(bool(r["starter"]) for r in rows)
            elif mode == "percentage":
                value = round(
                    sum(r["three_pointers_made"] for r in rows)
                    / sum(r["three_pointers_attempted"] for r in rows)
                    * 100,
                    4,
                )
            full_name = c.names[rows[0]["nba_player_id"]]
            label = f"{full_name}: {mode} {metric}"
            fact(label, value, rows, "player_game_stats", scope)
            facts[-1]["player_name"] = full_name
            facts[-1]["appearances"] = len(rows)
            if mode == "average":
                facts[-1]["numerator"] = sum(values)
                facts[-1]["denominator"] = len(rows)

        def leader(metric, rows):
            ids = {r["nba_game_id"] for r in rows}
            relevant = [
                r
                for r in c.data["player_game_stats"]
                if r["nba_game_id"] in ids
                and r["team_id"] == "NYK"
                and float(r.get("minutes") or 0) > 0
            ]
            totals = Counter()
            for r in relevant:
                totals[r["nba_player_id"]] += r[metric]
            maximum = max(totals.values())
            for pid, total in sorted(totals.items()):
                if total == maximum:
                    own = [r for r in relevant if r["nba_player_id"] == pid]
                    fact(
                        f"{metric} leader",
                        {"name": c.names[pid], "total": total},
                        own,
                        "player_game_stats",
                    )
            notes.append(
                f"Leader defined by total {metric}; all Knicks players compared, ties retained."
            )

        def scorelines(rows):
            for row in rows:
                fact(
                    "game_score",
                    {
                        k: row[k]
                        for k in (
                            "nba_game_id",
                            "game_date",
                            "home_team_id",
                            "away_team_id",
                            "home_score",
                            "away_score",
                        )
                    },
                    [row],
                )

        def clarify(reason, rows=None):
            nonlocal disposition, route
            disposition, route = "clarify", None
            notes.append(reason)
            if rows is not None:
                scorelines(rows)

        def refuse(reason):
            nonlocal disposition, route
            disposition, route = "refuse", None
            notes.append(reason)

        if cat == "exact_statistics":
            if n == 1:
                record(g)
            elif n == 2:
                fact("points", sum(c.own(x) for x in g), g)
            elif n in (3, 4, 25):
                average(
                    g,
                    {3: c.own, 4: c.margin, 25: c.allowed}[n],
                    {3: "points_per_game", 4: "average_margin", 25: "points_allowed_per_game"}[n],
                )
            elif n in (5, 6):
                selected = [x for x in g if (x["home_team_id"] == "NYK") == (n == 5)]
                fact(
                    "wins", c.record(selected)["wins"], selected, scope="home" if n == 5 else "away"
                )
            elif n == 7:
                fact("losses", c.record(g)["losses"], g)
            elif n in (8, 9, 10, 11):
                selected = c.extreme(c.margin if n in (8, 9) else c.own, n in (8, 10))
                scorelines(selected)
                if n in (8, 9):
                    fact("margin", c.margin(selected[0]), selected)
            elif n in (12, 13):
                selected = [x for x in g if (c.own(x) >= 120 if n == 12 else c.allowed(x) < 100)]
                fact("game_count", len(selected), selected)
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
                player_stat(*options[n])
            elif n in (18, 19, 20):
                leader({18: "assists", 19: "rebounds", 20: "steals"}[n], g)
            elif n == 24:
                selected = c.games_against("BOS")
                record(selected, "BOS")
        elif cat == "date_range_last_n":
            if n in (1, 10, 13):
                selected = (
                    g[-5:]
                    if n == 1
                    else g[:10]
                    if n == 10
                    else [x for x in g if x["season_type"] == "regular"][-15:]
                )
                record(selected)
            elif n in (2, 7, 12):
                selected = g[-{2: 10, 7: 8, 12: 5}[n] :]
                average(
                    selected,
                    {2: c.own, 7: c.margin, 12: c.allowed}[n],
                    {2: "points_per_game", 7: "average_margin", 12: "points_allowed_per_game"}[n],
                )
            elif n in (3, 11):
                player_stat(
                    "Brunson" if n == 3 else "Towns",
                    "points",
                    last=5 if n == 3 else 7,
                    scope="last appearances",
                )
            elif n == 4:
                selected = c.month(1)
                record(selected, "January 2026")
            elif n == 5:
                selected = [x for x in g if x["game_date"] > ALL_STAR_END]
                record(selected, "after February 15, 2026 (including postseason)")
            elif n == 6:
                selected = [x for x in c.month(12) if x["away_team_id"] == "NYK"]
                fact("wins", c.record(selected)["wins"], selected, scope="December road games")
            elif n == 8:
                selected = g[-3:]
                leader("points", selected)
            elif n == 9:
                selected = [x for x in g if "2026-03-01" <= x["game_date"] <= "2026-03-15"]
                fact("game_count", len(selected), selected)
            elif n == 14:
                pairs = [
                    (a, b)
                    for a, b in zip(g, g[1:], strict=False)
                    if (
                        date.fromisoformat(b["game_date"]) - date.fromisoformat(a["game_date"])
                    ).days
                    == 1
                    and b["game_date"].startswith("2026-02")
                ]
                fact(
                    "second_night_wins",
                    sum(c.margin(b) > 0 for _, b in pairs),
                    [b for _, b in pairs],
                )
                fact(
                    "both_games_won",
                    sum(c.margin(a) > 0 and c.margin(b) > 0 for a, b in pairs),
                    [x for pair in pairs for x in pair],
                )
                clarify(
                    "Back-to-back wins may mean winning the second night or "
                    "sweeping both games. "
                    "Both canonical counts supplied; ask which definition is intended."
                )
            elif n == 15:
                record(c.month(1), "January 2026")
                record(c.month(2), "February 2026")
        elif cat == "comparisons":
            if n == 1:
                for home in (True, False):
                    selected = [x for x in g if (x["home_team_id"] == "NYK") == home]
                    average(selected, c.own, "points_per_game", "home" if home else "away")
            elif n == 2:
                for name in ("Brunson", "Towns"):
                    player_stat(name, "points")
            elif n == 3:
                for team in ("BOS", "TOR"):
                    record(c.games_against(team), team)
                    average(c.games_against(team), c.margin, "average_margin", team)
                notes.append(
                    "Compare record/win percentage and scoring margin, not subjective play quality."
                )
            elif n == 4:
                record(g[:10], "first 10 games")
                record(g[-10:], "last 10 games")
            elif n in (5, 10):
                for win in (True, False):
                    selected = [x for x in g if (c.margin(x) > 0) == win]
                    ids = {x["nba_game_id"] for x in selected}
                    rows = [
                        r
                        for r in c.data["team_game_stats"]
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
                    fact(
                        "turnovers_per_game" if n == 5 else "field_goal_percentage",
                        value,
                        rows,
                        "team_game_stats",
                        "wins" if win else "losses",
                    )
            elif n == 6:
                for home in (True, False):
                    selected = [x for x in g if (x["home_team_id"] == "NYK") == home]
                    ids = {x["nba_game_id"] for x in selected}
                    rows = [
                        r
                        for r in c.data["player_game_stats"]
                        if r["nba_game_id"] in ids and r["team_id"] == "NYK" and not r["starter"]
                    ]
                    fact(
                        "bench_points_per_team_game",
                        round(sum(r["points"] for r in rows) / len(selected), 4),
                        rows,
                        "player_game_stats",
                        "home" if home else "away",
                    )
                notes.append(
                    "Bench means canonical starter=false rows; productivity "
                    "defined explicitly as"
                    " points per team game."
                )
            elif n == 7:
                clarify(
                    (
                        f"Archive contains {len(c.games_against('BOS'))} Boston games, not two. "
                        "Request "
                        "the intended dates or "
                        "compare all four explicitly."
                    ),
                    c.games_against("BOS"),
                )
            elif n == 8:
                player_stat("Towns", "rebounds")
                player_stat("Hart", "rebounds")
            elif n == 9:
                for period in (3, 4):
                    rows = [
                        r
                        for r in c.data["period_scores"]
                        if r["team_id"] == "NYK" and r["period"] == period
                    ]
                    fact(
                        "period_points_per_game",
                        round(sum(r["points"] for r in rows) / len(g), 4),
                        rows,
                        "period_scores",
                        f"quarter {period}",
                    )
            elif n == 11:
                player_stat(
                    "Bridges",
                    "points",
                    games=[x for x in g if x["game_date"] <= ALL_STAR_END],
                    scope="before All-Star break",
                )
                player_stat(
                    "Bridges",
                    "points",
                    games=[x for x in g if x["game_date"] > ALL_STAR_END],
                    scope="after All-Star break including postseason",
                )
            elif n in (12, 13):
                clarify(
                    (
                        "Define strength against a league benchmark or rating; "
                        "archive points alone "
                        "do not establish relative offense versus defense strength."
                    )
                    if n == 12
                    else (
                        "Define close-game and blowout margin thresholds before comparing; no "
                        "threshold is stated in the question."
                    )
                )
            elif n == 14:
                for conf in ("East", "West"):
                    selected = [x for x in g if c.conferences[c.opponent(x)] == conf]
                    record(selected, conf)
                    average(selected, c.margin, "average_margin", conf)
            elif n == 15:
                player_stat("Brunson", "points", last=5, scope="last 5 appearances")
                player_stat("Brunson", "points", scope="season appearances")
        elif cat == "single_game_narrative":
            route = "retrieval_rag"
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
                selected = c.games_against(opponents[n])
                if n == 20:
                    selected = [x for x in selected if c.margin(x) < 0]
                if len(selected) != 1:
                    clarify(
                        (
                            "No unique game/date is identified. Request a date and "
                            "avoid treating a "
                            "narrative premise as proven."
                        ),
                        selected,
                    )
                else:
                    scorelines(selected)
                    clarify(
                        "Game identity is unique, but causal/decisive premise "
                        "needs qualification. "
                        "Use corrected report interval as a descriptive example,"
                        " not causal proof."
                    )
            elif n == 6:
                selected = c.extreme(lambda x: abs(c.margin(x)), False)
                if len(selected) != 1:
                    clarify(
                        "Multiple games tie for smallest final margin; ask which date.", selected
                    )
                else:
                    scorelines(selected)
            elif n == 11:
                selected = c.extreme(c.margin)
                player_stat("Towns", "points", mode="total", games=selected)
                player_stat("Towns", "rebounds", mode="total", games=selected)
                player_stat("Towns", "assists", mode="total", games=selected)
                scorelines(selected)
            elif n == 15:
                selected = c.extreme(c.allowed, False)
                scorelines(selected)
                notes.append(
                    "Best defensive game defined as fewest opponent points, "
                    "not causal tactical "
                    "quality."
                )
            elif n == 18:
                rows = [
                    r for r in c.data["period_scores"] if r["team_id"] == "NYK" and r["period"] == 3
                ]
                low = min(r["points"] for r in rows)
                fact(
                    "fewest_third_quarter_points",
                    low,
                    [r for r in rows if r["points"] == low],
                    "period_scores",
                )
                clarify(
                    "Worst third quarter may mean fewest scored or worst net"
                    " margin. Specify the "
                    "metric before calling one worst."
                )
        elif cat == "turning_points":
            opponents = {
                1: "BOS",
                2: "TOR",
                3: "ATL",
                4: "CHI",
                6: "BOS",
                8: "CHA",
                9: "TOR",
                10: "ATL",
            }
            if n in opponents:
                selected = c.games_against(opponents[n])
                if n == 6:
                    selected = [x for x in selected if c.margin(x) < 0]
                clarify(
                    (
                        "Specify the game and scoring-run definition. A selected"
                        " bounded scoreboard "
                        "interval does not prove a causal turning point, collapse or drought that "
                        "cost the game."
                    ),
                    selected,
                )
            else:
                clarify(
                    "Specify comeback/run boundaries and whether biggest "
                    "means unanswered points,"
                    " net margin or duration. Corrected report intervals use an explicit "
                    "three-minute bound and cannot establish an unrestricted"
                    " season superlative."
                )
        elif cat == "follow_ups":
            clarify(
                (
                    "Supplied conversation does not pin a game, event interval or valid evidence."
                    " The assistant's asserted decisive Boston run is not canonical proof. Ask "
                    "for a game/date or cited interval."
                ),
                c.games_against("BOS"),
            )
            if n == 3:
                notes.append(
                    "Exact on-court lineup needs validated substitution reconstruction; player "
                    "box-score participation is not lineup evidence."
                )
        elif cat == "aliases_typos":
            if n in (1, 6):
                selected = c.games_against("BOS" if n == 1 else "ATL")
                record(selected, "BOS" if n == 1 else "ATL")
                notes.append(
                    "Alias resolves an aggregate opponent record; original retrieval_rag route "
                    "recommendation should be table_rag."
                )
            elif n in (4, 8, 9):
                selected = c.games_against("BOS" if n == 9 else "TOR")
                player_stat({4: "Towns", 8: "Bridges", 9: "Anunoby"}[n], "points", games=selected)
                notes.append(
                    "Offer canonical scoring average for all games against this opponent, "
                    "explicitly name the aggregate scope; subjective "
                    "played-well language is not "
                    "a factual label."
                )
            elif n in (2, 7):
                clarify(
                    (
                        "Typo/alias is understandable, but multiple matching "
                        "opponent games require a"
                        " date."
                    ),
                    c.games_against("BOS" if n == 2 else "CHI"),
                )
            elif n == 3:
                clarify("JB resolves to Jalen Brunson, but 'that game' has no provided context.")
            else:
                clarify(
                    "Typo is understandable; define scoring run or collapse before choosing a "
                    "season-wide superlative."
                )
        elif cat == "unsupported":
            if n in (1, 2, 3, 4, 5, 6, 7, 8, 15):
                refuse(
                    "Outside the immutable 2025-26 archive: no live, future, injury, trade, "
                    "betting or out-of-range evidence. Do not invent current facts."
                )
            elif n == 9:
                clarify(
                    (
                        "Lakers is an archived opponent with two games. This is ambiguous, not "
                        "unsupported solely because it names Lakers."
                    ),
                    c.games_against("LAL"),
                )
            elif n == 10:
                clarify(
                    (
                        "No prior game selection exists in the supplied context. List the archived "
                        "Boston dates and ask which."
                    ),
                    c.games_against("BOS"),
                )
            else:
                clarify(
                    "Missing game, player, time period or evaluation metric."
                    " Ask for the intended"
                    " scope; generic language alone does not prove an out-of-archive request."
                )
        else:
            raise ValueError(cat)

        unique_evidence = {r["canonical_id"]: r for r in evidence}
        factual_text = [
            f"{f['scope']} — {f['metric']}: {json.dumps(f['value'], ensure_ascii=False)}"
            for f in facts
        ]
        proposed = {
            "disposition": disposition,
            "answerable": disposition == "answer",
            "expected_route": route,
            "canonical_facts": facts,
            "required_facts": factual_text if disposition == "answer" else [],
            "claims": [
                {
                    "text": text,
                    "accepted_phrasings": [],
                    "evidence_ids": f["canonical_evidence_ids"],
                }
                for text, f in zip(factual_text, facts, strict=True)
            ]
            if disposition == "answer"
            else [],
            "canonical_evidence_ids": sorted(unique_evidence),
            "notes": notes,
        }
        differences = []
        if proposed["answerable"] != case["answerable"]:
            differences.append("original_answerability_requires_adjudication")
        if proposed["expected_route"] != case["expected_route"]:
            differences.append("original_route_requires_adjudication")
        if disposition == "clarify":
            differences.append("question_requires_scope_or_definition")
        if not differences and not facts and disposition == "answer":
            raise ValueError(f"Missing facts: {case['id']}")
        return {
            **case,
            "label_status": "agent_reviewed_owner_pending",
            "agent_review": {
                "status": "completed",
                "method": (
                    "independent canonical row arithmetic and question-by-question semantic review"
                ),
                "no_application_answer_used": True,
            },
            "owner_approval": None,
            "proposed_label": proposed,
            "canonical_sources": list(unique_evidence.values()),
            "discrepancies": differences,
            "remaining_owner_decisions": [
                (
                    "Approve or revise proposed disposition, metric/denominator and canonical "
                    "facts in category batch."
                ),
                (
                    "Approve accepted answer phrasings and claim-level citation mappings after "
                    "verified target identity."
                ),
            ],
        }

    return [review_case(case) for case in cases], common


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--questions", type=Path, default=QUESTIONS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    raw = args.baseline.read_bytes()
    payload = json.loads(raw)
    cases = [json.loads(line) for line in args.questions.read_text().splitlines() if line.strip()]
    labels, policy = review_cases(payload, cases)
    identity = {
        "baseline_file_sha256": hashlib.sha256(raw).hexdigest(),
        "canonical_data_sha256": digest(
            {k: v for k, v in payload["data"].items() if k != "reports"}
        ),
        "questions_file_sha256": hashlib.sha256(args.questions.read_bytes()).hexdigest(),
        "data_version": payload["manifest"]["version"],
    }
    for label in labels:
        label.update(identity)
    args.output.mkdir(parents=True, exist_ok=True)
    labels_path = args.output / "labels.jsonl"
    labels_path.write_text(
        "".join(json.dumps(label, sort_keys=True, separators=(",", ":")) + "\n" for label in labels)
    )
    summary = {
        "schema_version": 1,
        "identity": identity,
        "policy": policy,
        "case_count": len(labels),
        "original_category_counts": dict(Counter(c["category"] for c in labels)),
        "proposed_dispositions": dict(Counter(c["proposed_label"]["disposition"] for c in labels)),
        "agent_reviewed": len(labels),
        "owner_approved": 0,
        "gold_labels_eligible": False,
        "labels_file_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
        "discrepancies": [
            {
                "id": c["id"],
                "question": c["question"],
                "issues": c["discrepancies"],
                "proposed_label": c["proposed_label"],
            }
            for c in labels
            if c["discrepancies"]
        ],
        "blocking_integration_issues": [
            (
                "Canonical NBA IDs must map to verified candidate retrieval evidence IDs; "
                "current runtime IDs may differ."
            ),
            (
                "Accepted phrase variants must be batch-reviewed. Exact English strings and "
                "numeric rounding cannot be inferred from a dry-run answer."
            ),
            (
                "Do not treat clarified questions as removed semantic tests or claim Recall@5"
                " from a smaller replacement set."
            ),
            (
                "Original question, category, answerable and route fields are preserved. "
                "Proposed adjudications do not silently rewrite the evaluation set."
            ),
            (
                "The evaluation harness currently treats all answerable=false cases as "
                "refused and cannot distinguish correct clarification from inappropriate "
                "refusal."
            ),
        ],
    }
    (args.output / "review.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = [
        "# Evaluation label review",
        "",
        f"All {len(labels)} fixed questions reviewed against canonical rows. "
        "Owner approvals: **0**. Gold-label eligibility: **blocked**.",
        "",
        f"Proposed dispositions: {json.dumps(summary['proposed_dispositions'], sort_keys=True)}.",
        "",
        (
            "Original questions, categories and expected labels are preserved. "
            "Recommendations below are explicit owner adjudications, not relabelled "
            "passing results."
        ),
        "",
        (
            "Player averages use appearances; last-N player windows use appearances "
            "rather than team games. All-Star boundary is after February 15, 2026, "
            "verified against [NBA All-Star](https://www.nba.com/allstar/2026/). All "
            "arithmetic uses canonical archive rows."
        ),
        "",
        (
            "Every factual claim has typed values, metric scope, canonical source IDs and"
            " source-row hashes in labels.jsonl. These IDs still need mapping to the "
            "verified runtime/index; accepted prose variants and rounding are pending "
            "owner batch review."
        ),
        "",
        "| Question | Proposed behavior | Canonical facts / decision |",
        "|---|---|---|",
    ]
    for label in labels:
        p = label["proposed_label"]
        detail = "; ".join(p["required_facts"] or p["notes"])
        lines.append(
            f"| {label['id']}: {label['question']} | {p['disposition']} | "
            f"{detail.replace('|', '/')} |"
        )
    (args.output / "review.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "case_count",
                    "proposed_dispositions",
                    "agent_reviewed",
                    "owner_approved",
                    "labels_file_sha256",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
