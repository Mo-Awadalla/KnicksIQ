"""Requested comparisons and profiles over real HTTP, SQL, and isolated Redis."""

import gzip
import json
import os
from collections import defaultdict
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.game import Game
from app.models.player import Player
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, SHA, request
from sqlalchemy import select


async def test_complete_requested_comparisons_and_player_profile(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,  # noqa: F811
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = sorted(
        [g for g in raw["games"] if "NYK" in {g["home_team_id"], g["away_team_id"]}],
        key=lambda g: (g["game_date"], g["nba_game_id"]),
    )
    by_id = {g["nba_game_id"]: g for g in games}
    players = {p["nba_player_id"]: p["full_name"] for p in raw["players"]}
    boxes = [s for s in raw["player_game_stats"] if s["team_id"] == "NYK"]
    team_boxes = {s["nba_game_id"]: s for s in raw["team_game_stats"] if s["team_id"] == "NYK"}
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        game_ids = {g.nba_game_id: g.id for g in (await db.execute(select(Game))).scalars()}
        player_ids = {p.nba_player_id: p.id for p in (await db.execute(select(Player))).scalars()}
    directory = Path(os.environ.get("KNICKSIQ_COMPARATIVE_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    record_property("comparative_artifacts", str(directory))
    failures = []

    def own(g):
        return g["home_score"] if g["home_team_id"] == "NYK" else g["away_score"]

    def allowed(g):
        return g["away_score"] if g["home_team_id"] == "NYK" else g["home_score"]

    async def exercise(name, question):
        body, capture = await request(client, local_redis, monkeypatch, directory, name, question)
        claims = [
            c["metadata"]["claim"] for c in body["citations"] if c["type"] == "verified_claim"
        ]
        return body, claims, capture

    for metric in ("assists", "rebounds", "steals"):
        totals = defaultdict(int)
        for row in boxes:
            totals[row["nba_player_id"]] += row[metric]
        maximum = max(totals.values())
        leaders = sorted(players[p] for p, value in totals.items() if value == maximum)
        body, claims, _ = await exercise(f"leader-{metric}", f"Who led the Knicks in {metric}?")
        matched = [c for c in claims if c["metric_id"] == f"{metric}:leaders"]
        if not matched or matched[0]["value"] != {"leaders": leaders, "total": maximum}:
            failures.append((metric, "wrong leaders", claims))
        elif not all(name in body["answer"] for name in leaders):
            failures.append((metric, "leaders missing from delivered answer"))

    home_away = [
        ("Home", [g for g in games if g["home_team_id"] == "NYK"]),
        ("Away", [g for g in games if g["away_team_id"] == "NYK"]),
    ]
    wins_losses = [
        ("Wins", [g for g in games if own(g) > allowed(g)]),
        ("Losses", [g for g in games if own(g) < allowed(g)]),
    ]
    months = [
        (name, [g for g in games if int(g["game_date"][5:7]) == month])
        for name, month in [("January", 1), ("February", 2)]
    ]
    opponents = [
        (team, [g for g in games if team in {g["home_team_id"], g["away_team_id"]}])
        for team in ("BOS", "TOR")
    ]
    windows = [("First 10 games", games[:10]), ("Last 10 games", games[-10:])]
    cases = [
        (
            "offense",
            "Compare the Knicks' offense at home and on the road.",
            home_away,
            "points_per_game",
        ),
        (
            "defense",
            "Compare the Knicks' average points allowed at home and on the road.",
            home_away,
            "points_allowed_per_game",
        ),
        (
            "turnovers",
            "Compare wins and losses by average turnover count.",
            wins_losses,
            "turnovers_per_game",
        ),
        (
            "bench",
            "Was the bench more productive in home or away games?",
            home_away,
            "bench_points_per_team_game",
        ),
        (
            "shooting",
            "Did the Knicks shoot better in wins or losses?",
            wins_losses,
            "field_goal_percentage",
        ),
        ("months", "Compare the Knicks record in January and February.", months, "record"),
        ("windows", "Compare their first 10 games with their last 10 games.", windows, "record"),
        (
            "opponents",
            "Did the Knicks play better against Boston or Toronto?",
            opponents,
            "record_margin",
        ),
    ]
    for name, question, groups, metric in cases:
        response, claims, capture = await exercise(name, question)
        if any(not population for _, population in groups):
            # Portable CI has no away games: do not invent a comparison denominator.
            if response["citations"] or not any(
                tool["result"]["status"] == "incomplete_coverage" for tool in capture["tools"]
            ):
                failures.append((name, "unavailable group must reject partial comparison"))
            continue
        matched = {
            c["window"]["comparison_group"]: c
            for c in claims
            if c["metric_id"] == "team_comparison"
        }
        if set(matched) != {label for label, _ in groups}:
            failures.append((name, "missing comparison populations", claims))
            continue
        for label, population in groups:
            ids = {g["nba_game_id"] for g in population}
            count = len(population)
            if metric == "points_per_game":
                values = {metric: sum(own(g) for g in population) / count}
            elif metric == "points_allowed_per_game":
                values = {metric: sum(allowed(g) for g in population) / count}
                assert values[metric] != sum(own(g) for g in population) / count
            elif metric == "turnovers_per_game":
                values = {metric: sum(team_boxes[i]["turnovers"] for i in ids) / count}
            elif metric == "field_goal_percentage":
                values = {
                    metric: 100
                    * sum(team_boxes[i]["field_goals_made"] for i in ids)
                    / sum(team_boxes[i]["field_goals_attempted"] for i in ids)
                }
            elif metric == "bench_points_per_team_game":
                values = {
                    metric: sum(
                        s["points"] for s in boxes if s["nba_game_id"] in ids and not s["starter"]
                    )
                    / count
                }
            else:
                wins = sum(own(g) > allowed(g) for g in population)
                values: dict[str, int | float] = {
                    "games": count,
                    "wins": wins,
                    "losses": count - wins,
                }
                if metric == "record_margin":
                    values["average_margin"] = sum(own(g) - allowed(g) for g in population) / count
            claim = matched[label]
            if metric == "points_allowed_per_game":
                assert claim["subject_id"] == "team:NYK"
                assert claim["sample_size"] == count
                assert claim["denominator"] == count
                assert "points_allowed_per_game" in claim["statement"]
            if claim["value"] != pytest.approx(values) or set(claim["game_ids"]) != {
                game_ids[i] for i in ids
            }:
                failures.append((name, label, "wrong values or authorized population", claim))

    _, claims, _ = await exercise(
        "quarters", "Compare the Knicks' third-quarter and fourth-quarter scoring."
    )
    quarters = {
        c["filters"].get("periods", [None])[0]: c
        for c in claims
        if c["metric_id"] == "period_points:average"
    }
    for period in (3, 4):
        rows = [r for r in raw["period_scores"] if r["team_id"] == "NYK" and r["period"] == period]
        if period not in quarters or quarters[period]["value"] != pytest.approx(
            sum(r["points"] for r in rows) / len(rows)
        ):
            failures.append(("quarter", period, "missing or wrong scoring", claims))

    brunson = [s for s in boxes if s["nba_player_id"] == 1628973 and s["minutes"] > 0]
    brunson.sort(key=lambda s: (by_id[s["nba_game_id"]]["game_date"], s["nba_game_id"]))
    _, claims, _ = await exercise(
        "player-windows", "Compare Brunson's last 5 games with his season average."
    )
    expected = [
        {game_ids[s["nba_game_id"]] for s in population} for population in (brunson[-5:], brunson)
    ]
    for population, ids in zip((brunson[-5:], brunson), expected, strict=True):
        matched = [
            c for c in claims if c["metric_id"] == "points:average" and set(c["game_ids"]) == ids
        ]
        if not matched or matched[0]["value"] != pytest.approx(
            sum(s["points"] for s in population) / len(population)
        ):
            failures.append(
                ("player-windows", "missing exact operand population", sorted(ids), claims)
            )

    unsupported_periods = [
        ("period-total", "How many total points did the Knicks score in the third quarter?"),
        ("period-rebounds", "How many rebounds did the Knicks have in the third quarter?"),
        ("period-player", "How many points did Brunson score in the third quarter?"),
    ]
    for name, question in unsupported_periods:
        response, _, capture = await exercise(name, question)
        if response["citations"] or not any(
            tool["result"]["status"] == "unsupported_metric_or_scope" for tool in capture["tools"]
        ):
            failures.append(
                (name, "unsupported quarter calculation must not answer another metric")
            )

    maximum = max(own(g) - allowed(g) for g in games if own(g) > allowed(g))
    biggest = [g for g in games if own(g) - allowed(g) == maximum]
    body, claims, _ = await exercise("towns-profile", "What did Towns do in the biggest win?")
    for game in biggest:
        row = next(
            s
            for s in boxes
            if s["nba_game_id"] == game["nba_game_id"] and s["nba_player_id"] == 1626157
        )
        for metric in ("points", "rebounds", "assists"):
            matched = [
                c
                for c in claims
                if c["metric_id"] == f"{metric}:total"
                and c["subject_id"] == f"player:{player_ids[1626157]}"
                and c["game_ids"] == [game_ids[game["nba_game_id"]]]
            ]
            if not matched or matched[0]["value"] != row[metric]:
                failures.append(("towns-profile", game["nba_game_id"], metric, claims))
        scores = [
            c
            for c in claims
            if c["metric_id"] == "game_score" and c["game_ids"] == [game_ids[game["nba_game_id"]]]
        ]
        opponent = game["away_team_id"] if game["home_team_id"] == "NYK" else game["home_team_id"]
        if (
            not scores
            or scores[0]["value"] != {"NYK": own(game), opponent: allowed(game)}
            or game["game_date"] not in body["answer"]
        ):
            failures.append(("towns-profile", "missing delivered game identity and score", claims))
    with (directory / "summary.json").open("x") as artifact:
        json.dump({"cases": 16, "bundle_sha256": SHA, "failures": failures}, artifact, indent=2)
    assert not failures, failures
