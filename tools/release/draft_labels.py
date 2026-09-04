"""Draft canonical evidence for all fixed evaluation questions; never mark reviewed.

Semantic questions without a unique game need owner adjudication. Canonical source
IDs use NBA game identity until a verified candidate index provides vector IDs.
"""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "release-artifacts/2025-26/release-candidate.json"
QUESTIONS = ROOT / "apps/api/app/evaluation/questions.jsonl"
OUTPUT = ROOT / "docs/release-evidence/evaluation-label-drafts.jsonl"


def main():
    bundle = json.loads(BASELINE.read_text())
    data = bundle["data"]
    games = sorted(data["games"], key=lambda g: (g["game_date"], g["nba_game_id"]))
    players = {p["nba_player_id"]: p["full_name"] for p in data["players"]}
    stats = data["player_game_stats"]
    team_stats = data["team_game_stats"]
    baseline_hash = hashlib.sha256(BASELINE.read_bytes()).hexdigest()

    def points(g):
        return g["home_score"] if g["home_team_id"] == "NYK" else g["away_score"]

    def against(g):
        return g["away_score"] if g["home_team_id"] == "NYK" else g["home_score"]

    def summary(selected):
        n = len(selected)
        wins = sum(points(g) > against(g) for g in selected)
        return {
            "games": n,
            "wins": wins,
            "losses": n - wins,
            "points": sum(points(g) for g in selected),
            "points_allowed": sum(against(g) for g in selected),
            "points_per_game": round(sum(points(g) for g in selected) / n, 4) if n else None,
            "points_allowed_per_game": round(sum(against(g) for g in selected) / n, 4)
            if n
            else None,
            "average_margin": round(sum(points(g) - against(g) for g in selected) / n, 4)
            if n
            else None,
        }

    drafts = []
    for line in QUESTIONS.read_text().splitlines():
        case = json.loads(line)
        text = case["question"].lower()
        selected = games
        blockers = [
            "Owner batch approval pending.",
            "Active archive identity unverified.",
            "Map canonical evidence IDs to verified candidate retrieval point IDs.",
        ]
        filters = {}
        for terms, team in [
            (["boston", "bos", "celts", "c's"], "BOS"),
            (["toronto", "raps"], "TOR"),
            (["atlanta", "atl"], "ATL"),
            (["chicago", "chi"], "CHI"),
            (["charlotte"], "CHA"),
            (["lakers"], "LAL"),
        ]:
            if any(re.search(r"\b" + re.escape(term) + r"\b", text) for term in terms):
                selected = [g for g in selected if team in [g["home_team_id"], g["away_team_id"]]]
                filters["opponent"] = team
        if "regular-season" in text:
            selected = [g for g in selected if g["season_type"] == "regular"]
        last = re.search(r"(?:last|final) (\d+)", text)
        first = re.search(r"first (\d+)", text)
        if last and not (first and "compare" in text):
            selected = selected[-int(last[1]) :]
        elif first:
            selected = selected[: int(first[1])]
        for word, month in [
            ("january", "01"),
            ("february", "02"),
            ("december", "12"),
            ("march", "03"),
        ]:
            if word in text and "compare" not in text:
                selected = [g for g in selected if g["game_date"][5:7] == month]
        if "march 1 and march 15" in text:
            selected = [g for g in selected if int(g["game_date"][8:10]) <= 15]
        if "all-star" in text:
            blockers.append(
                "Owner must pin All-Star break boundary before this comparison can be labelled."
            )
        if "back-to-back" in text:
            blockers.append(
                "Owner must define whether a back-to-back win means the second game or both games."
            )
        if "biggest win" in text:
            best = max(points(g) - against(g) for g in selected)
            selected = [g for g in selected if points(g) - against(g) == best]
        if "worst loss" in text:
            worst = min(points(g) - against(g) for g in selected)
            selected = [g for g in selected if points(g) - against(g) == worst]
        if "highest-scoring" in text or "lowest-scoring" in text:
            extreme = (max if "highest" in text else min)(points(g) for g in selected)
            selected = [g for g in selected if points(g) == extreme]
        if "closest" in text:
            closest = min(abs(points(g) - against(g)) for g in selected)
            selected = [g for g in selected if abs(points(g) - against(g)) == closest]
        if "best defensive game" in text:
            lowest = min(against(g) for g in selected)
            selected = [g for g in selected if against(g) == lowest]
        game_ids = {g["nba_game_id"] for g in selected}
        relevant_stats = [
            p for p in stats if p["nba_game_id"] in game_ids and p["team_id"] == "NYK"
        ]
        player_facts = []
        for player_id in sorted({p["nba_player_id"] for p in relevant_stats}):
            rows = [
                p
                for p in relevant_stats
                if p["nba_player_id"] == player_id and float(p.get("minutes") or 0) > 0
            ]
            if not rows:
                continue
            totals = {
                key: sum(float(p.get(key) or 0) for p in rows)
                for key in [
                    "points",
                    "rebounds",
                    "assists",
                    "steals",
                    "blocks",
                    "turnovers",
                    "three_pointers_made",
                    "three_pointers_attempted",
                ]
            }
            player_facts.append(
                {
                    "player_id": player_id,
                    "name": players.get(player_id),
                    "appearances": len(rows),
                    "totals": totals,
                    "per_appearance": {k: round(v / len(rows), 4) for k, v in totals.items()},
                    "starts": sum(bool(p.get("starter")) for p in rows),
                    "double_doubles": sum(
                        sum(
                            float(p.get(k) or 0) >= 10
                            for k in ["points", "rebounds", "assists", "steals", "blocks"]
                        )
                        >= 2
                        for p in rows
                    ),
                    "evidence_ids": [f"box:{p['nba_game_id']}:{player_id}" for p in rows],
                }
            )
        ambiguous = (
            case["category"] in ["single_game_narrative", "turning_points", "aliases_typos"]
            and len(selected) > 1
        )
        if ambiguous:
            blockers.append(
                "Question identifies multiple games; approve clarification or pin a game/context."
            )
        if case["category"] == "follow_ups":
            blockers.append(
                "Review context and structured state before resolving the referenced game/run."
            )
        if case["category"] in ["single_game_narrative", "turning_points", "follow_ups"]:
            blockers.append(
                "Run audit unresolved; causal/decisive descriptions must not be labelled factual."
            )
        draft = {
            **case,
            "label_status": "draft_needs_owner_review",
            "baseline_sha256": baseline_hash,
            "owner_approval": None,
            "draft_filters": filters,
            "draft_canonical_facts": {
                "scope": "regular season and postseason unless filtered",
                "record_and_scoring": summary(selected),
                "home": summary([g for g in selected if g["home_team_id"] == "NYK"]),
                "away": summary([g for g in selected if g["away_team_id"] == "NYK"]),
                "games_scoring_at_least_120": sum(points(g) >= 120 for g in selected),
                "games_allowing_under_100": sum(against(g) < 100 for g in selected),
                "players": player_facts,
                "scorelines": [
                    {
                        k: g[k]
                        for k in [
                            "nba_game_id",
                            "game_date",
                            "home_team_id",
                            "away_team_id",
                            "home_score",
                            "away_score",
                        ]
                    }
                    for g in selected
                ],
                "quarter_totals": {
                    str(period): sum(
                        p["points"]
                        for p in data["period_scores"]
                        if p["nba_game_id"] in game_ids
                        and p["team_id"] == "NYK"
                        and p["period"] == period
                    )
                    for period in range(1, 5)
                },
                "team_box_totals": {
                    key: sum(
                        float(p.get(key) or 0)
                        for p in team_stats
                        if p["nba_game_id"] in game_ids and p["team_id"] == "NYK"
                    )
                    for key in ["turnovers", "field_goals_made", "field_goals_attempted"]
                },
            },
            "draft_evidence_ids": [f"game:{g['nba_game_id']}" for g in selected],
            "blocking_label_decisions": blockers,
        }
        if case["category"] == "unsupported":
            draft["draft_canonical_facts"] = {
                "archive_date_range": [games[0]["game_date"], games[-1]["game_date"]],
                "supported_lakers_games": len(
                    [g for g in games if "LAL" in [g["home_team_id"], g["away_team_id"]]]
                ),
            }
            draft["blocking_label_decisions"].append(
                "Confirm refusal versus clarification. Some questions refer to archived opponents."
            )
        drafts.append(draft)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "".join(json.dumps(d, sort_keys=True, separators=(",", ":")) + "\n" for d in drafts)
    )
    print(f"Wrote {len(drafts)} drafts; zero reviewed labels. Source SHA-256 {baseline_hash}.")


if __name__ == "__main__":
    main()
