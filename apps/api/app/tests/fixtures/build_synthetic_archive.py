"""Reproduce synthetic HTTP test data; never read private release data or labels."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from app.services.release_bundle import build_bundle, canonical_json, read_bundle, validate_bundle


def build(output: Path) -> str:
    seed = Path(__file__).resolve().parents[2] / "core/seed/teams.json"
    teams = json.loads(seed.read_text())
    opponents = [t["id"] for t in teams if t["id"] not in {"NYK", "ATL"}]
    roster = [
        (1628973, "Jalen Brunson", "PG", "11"),
        (1626157, "Karl-Anthony Towns", "C", "32"),
        (1628404, "Josh Hart", "SG", "3"),
        (1628969, "Mikal Bridges", "SF", "25"),
        (1628384, "OG Anunoby", "SF", "8"),
        (1629011, "Mitchell Robinson", "C", "23"),
        (1630540, "Miles McBride", "PG", "2"),
        *(
            (identity, f"Synthetic Reserve{chr(65 + i)}", "PF", str(i + 40))
            for i, identity in enumerate(
                [1628368, 1629216, 1629723, 1641748, 1627752, *range(9900100, 9900108)]
            )
        ),
    ]
    players = [
        {
            "nba_player_id": identity,
            "full_name": name,
            "team_id": "NYK",
            "position": position,
            "jersey_number": jersey,
        }
        for identity, name, position, jersey in roster
    ]
    away_players = {}
    for i, team in enumerate(t for t in teams if t["id"] != "NYK"):
        identity = 9910000 + i
        away_players[team["id"]] = identity
        players.append(
            {
                "nba_player_id": identity,
                "full_name": f"Synthetic {team['id']} Player",
                "team_id": team["id"],
                "position": "SG",
                "jersey_number": "99",
            }
        )
    content = {
        name: []
        for name in (
            "games",
            "events",
            "period_scores",
            "team_game_stats",
            "player_game_stats",
            "reports",
        )
    }
    content.update(teams=teams, players=players, generated_stat_facts=[])
    closest = ["0022500372", "0022501016", "0042500122", "0042500123", "0042500402", "0042500404"]

    def stats(game_id, nba_id, team, points, i, minutes=32.0):
        threes = points // 8
        twos = (points - threes * 3) // 2
        free = points - threes * 3 - twos * 2
        return {
            "nba_game_id": game_id,
            "nba_player_id": nba_id,
            "team_id": team,
            "points": points,
            "minutes": minutes,
            "starter": bool(minutes and i % 3),
            "field_goals_made": twos + threes,
            "field_goals_attempted": twos + threes + 6,
            "three_pointers_made": threes,
            "three_pointers_attempted": threes + 3,
            "free_throws_made": free,
            "free_throws_attempted": free + 1,
            "offensive_rebounds": 2 if minutes else 0,
            "defensive_rebounds": i % 11 if minutes else 0,
            "rebounds": 2 + i % 11 if minutes else 0,
            "assists": i % 9 if minutes else 0,
            "steals": i % 3 if minutes else 0,
            "blocks": i % 2 if minutes else 0,
            "turnovers": i % 4 if minutes else 0,
            "personal_fouls": i % 5 if minutes else 0,
        }

    for i in range(101):
        identity = closest[i] if i < 6 else "0022500320" if i == 6 else f"synthetic-game-{i:03d}"
        opponent = "BOS" if i == 6 else "ATL" if 7 <= i <= 15 else opponents[i % len(opponents)]
        own = 104 if i == 6 else 98 + i % 36
        other = 124 if i == 6 else own + (-1 if i < 6 else -5 if i % 2 or opponent == "BOS" else 7)
        day = date(2025, 12, 2) if i == 6 else date(2025, 10, 22) + timedelta(days=round(i * 2.35))
        phase = "playoffs" if i >= 80 or 13 <= i <= 15 else "regular"
        content["games"].append(
            {
                "nba_game_id": identity,
                "season": "2025-26",
                "game_date": str(day),
                "home_team_id": "NYK",
                "away_team_id": opponent,
                "home_score": own,
                "away_score": other,
                "status": "final",
                "season_type": phase,
                "data_status": "analysis_ready",
                "source_name": "synthetic-ci-fixture",
                "source_url": f"https://example.invalid/fixture/{identity}",
                "source_game_id": identity,
                "source_fetched_at": "2026-07-01T00:00:00+00:00",
                "source_payload_hash": hashlib.sha256(f"synthetic:{identity}".encode()).hexdigest(),
            }
        )
        hart_dnp = i % 4 == 0
        points = [22 + i % 7, 18 + i % 5, 0 if hart_dnp else 10 + i % 7, 12 + i % 6]
        points += [own - sum(points)] + [0] * 15
        rows = [
            stats(
                identity,
                player[0],
                "NYK",
                points[j],
                i + j,
                0 if (j == 2 and hart_dnp) or j >= 7 else 32,
            )
            for j, player in enumerate(roster)
        ]
        rows.append(stats(identity, away_players[opponent], opponent, other, i, 48))
        content["player_game_stats"].extend(rows)
        for team in ("NYK", opponent):
            grouped = [r for r in rows if r["team_id"] == team]
            content["team_game_stats"].append(
                {
                    "nba_game_id": identity,
                    "team_id": team,
                    **{
                        k: sum(r[k] for r in grouped)
                        for k in grouped[0]
                        if k
                        not in {"nba_game_id", "nba_player_id", "team_id", "starter", "minutes"}
                    },
                }
            )
            scores = (
                ([100, 3, 0, 1] if team == "NYK" else [100, 12, 12, 0])
                if i == 6
                else (
                    [own // 4] * 3 + [own - 3 * (own // 4)]
                    if team == "NYK"
                    else [other // 4] * 3 + [other - 3 * (other // 4)]
                )
            )
            content["period_scores"].extend(
                {"nba_game_id": identity, "team_id": team, "period": p, "points": value}
                for p, value in enumerate(scores, 1)
            )
        home = away = 0

        def event(sequence, period, clock, team, value, opponent=opponent, identity=identity):
            nonlocal home, away
            home += value if team == "NYK" else 0
            away += value if team == opponent else 0
            content["events"].append(
                {
                    "nba_game_id": identity,
                    "sequence": sequence,
                    "period": period,
                    "clock": clock,
                    "team_id": team,
                    "nba_player_id": roster[0][0] if team == "NYK" else away_players[opponent],
                    "event_type": "made_shot",
                    "description": f"Synthetic {team} scoring event",
                    "home_score": home,
                    "away_score": away,
                    "score_margin": home - away,
                    "shot_type": "3pt" if value == 3 else "2pt",
                    "shot_result": "made",
                }
            )

        if i == 6:
            for sequence in range(1, 101):
                event(
                    sequence,
                    1,
                    f"{11 - sequence // 10:02d}:00",
                    "NYK" if sequence % 2 else opponent,
                    2,
                )
            event(111, 2, "11:00", "NYK", 2)
            for sequence, clock in zip(
                [128, 131, 137, 140, 144, 146],
                ["10:07", "09:50", "09:30", "09:00", "08:40", "08:25"],
                strict=True,
            ):
                event(sequence, 2, clock, opponent, 2)
            event(147, 2, "08:00", "NYK", 1)
            for sequence, clock, value in zip(
                [282, 290, 293, 295, 299],
                ["02:29", "02:00", "01:30", "01:00", "00:03"],
                [2, 2, 2, 3, 3],
                strict=True,
            ):
                event(sequence, 3, clock, opponent, value)
            event(300, 4, "00:00", "NYK", 1)
        else:
            event(1, 1, "12:00", "NYK", own)
            event(2, 4, "00:00", opponent, other)
        content["reports"].append(
            {
                "nba_game_id": identity,
                "report_type": "postgame",
                "reviewed": True,
                "title": f"Synthetic Knicks versus {opponent} fixture {i}",
                "summary": "Fabricated HTTP test data. This report describes no actual game.",
            }
        )
    payload = {
        "manifest": {
            "version": "2025-26.synthetic-ci.1",
            "season": "2025-26",
            "source": "synthetic-ci-fixture",
            "expected_games": 101,
            "expected_game_ids": [g["nba_game_id"] for g in content["games"]],
        },
        "data": content,
        "review_manifest": {
            "approvals": {
                r["nba_game_id"]: hashlib.sha256(
                    canonical_json({k: v for k, v in r.items() if k != "reviewed"})
                ).hexdigest()
                for r in content["reports"]
            }
        },
    }
    digest = build_bundle(payload, output)
    validate_bundle(read_bundle(output, digest))
    return digest


if __name__ == "__main__":
    target = Path(__file__).with_name("synthetic-archive.json.gz")
    print(build(target))
