"""Recover the cached season into a deterministic release-candidate document."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.models.bad_stretch import BadStretch
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
from app.models.scoring_run import ScoringRun
from app.models.team import Team
from app.services.release_bundle import canonical_json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from worker_app.adapters.nba_api_source import NbaApiDataSource
from worker_app.core.config import get_settings
from worker_app.core.db import AsyncSessionLocal

_PERIOD_SCORE = re.compile(r"^period(\d+)Score$")
_ISO_MINUTES = re.compile(r"^PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$")
_CLOCK_MINUTES = re.compile(r"^(\d+):(\d+(?:\.\d+)?)$")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


def _int(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    if value in (None, ""):
        return 0
    return int(float(value))


def _minutes(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = _ISO_MINUTES.match(text)
    if match:
        return int(match.group(1) or 0) + float(match.group(2) or 0) / 60
    match = _CLOCK_MINUTES.match(text)
    if match:
        return int(match.group(1)) + float(match.group(2)) / 60
    try:
        return float(text)
    except ValueError:
        return 0.0


def normalize_box_score(nba_game_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Map nba_api v3 names to the stable release schema."""
    team_stats: list[dict[str, Any]] = []
    for raw in payload.get("team_stats") or []:
        row = _json_safe(raw)
        team_stats.append(
            {
                "nba_game_id": nba_game_id,
                "team_id": row["teamTricode"],
                "points": _int(row, "points"),
                "field_goals_made": _int(row, "fieldGoalsMade"),
                "field_goals_attempted": _int(row, "fieldGoalsAttempted"),
                "three_pointers_made": _int(row, "threePointersMade"),
                "three_pointers_attempted": _int(row, "threePointersAttempted"),
                "free_throws_made": _int(row, "freeThrowsMade"),
                "free_throws_attempted": _int(row, "freeThrowsAttempted"),
                "offensive_rebounds": _int(row, "reboundsOffensive"),
                "defensive_rebounds": _int(row, "reboundsDefensive"),
                "rebounds": _int(row, "reboundsTotal"),
                "assists": _int(row, "assists"),
                "steals": _int(row, "steals"),
                "blocks": _int(row, "blocks"),
                "turnovers": _int(row, "turnovers"),
                "personal_fouls": _int(row, "foulsPersonal"),
                "plus_minus": _int(row, "plusMinusPoints"),
            }
        )

    player_stats: list[dict[str, Any]] = []
    player_definitions: list[dict[str, Any]] = []
    for raw in payload.get("player_stats") or []:
        row = _json_safe(raw)
        nba_player_id = _int(row, "personId")
        if not nba_player_id:
            continue
        position = str(row.get("position") or "").strip() or None
        team_id = str(row.get("teamTricode") or "").strip()
        full_name = " ".join(
            part
            for part in (str(row.get("firstName") or ""), str(row.get("familyName") or ""))
            if part
        ).strip()
        player_definitions.append(
            {
                "nba_player_id": nba_player_id,
                "full_name": full_name or str(row.get("nameI") or nba_player_id),
                "team_id": team_id,
                "position": position,
                "jersey_number": str(row.get("jerseyNum") or "").strip() or None,
            }
        )
        player_stats.append(
            {
                "nba_game_id": nba_game_id,
                "nba_player_id": nba_player_id,
                "team_id": team_id,
                "starter": position is not None,
                "position": position,
                "minutes": round(_minutes(row.get("minutes")), 4),
                "points": _int(row, "points"),
                "field_goals_made": _int(row, "fieldGoalsMade"),
                "field_goals_attempted": _int(row, "fieldGoalsAttempted"),
                "three_pointers_made": _int(row, "threePointersMade"),
                "three_pointers_attempted": _int(row, "threePointersAttempted"),
                "free_throws_made": _int(row, "freeThrowsMade"),
                "free_throws_attempted": _int(row, "freeThrowsAttempted"),
                "offensive_rebounds": _int(row, "reboundsOffensive"),
                "defensive_rebounds": _int(row, "reboundsDefensive"),
                "rebounds": _int(row, "reboundsTotal"),
                "assists": _int(row, "assists"),
                "steals": _int(row, "steals"),
                "blocks": _int(row, "blocks"),
                "turnovers": _int(row, "turnovers"),
                "personal_fouls": _int(row, "foulsPersonal"),
                "plus_minus": _int(row, "plusMinusPoints"),
            }
        )

    period_scores: list[dict[str, Any]] = []
    for raw in payload.get("line_scores") or []:
        row = _json_safe(raw)
        team_id = str(row.get("teamTricode") or "").strip()
        for key, value in row.items():
            match = _PERIOD_SCORE.match(key)
            if match and value is not None:
                period_scores.append(
                    {
                        "nba_game_id": nba_game_id,
                        "team_id": team_id,
                        "period": int(match.group(1)),
                        "points": int(value),
                    }
                )
    return {
        "team_game_stats": team_stats,
        "player_game_stats": player_stats,
        "period_scores": period_scores,
        "players": player_definitions,
    }


async def _canonical_games(db: AsyncSession, season: str) -> list[Game]:
    return list(
        (
            await db.execute(
                select(Game)
                .where(Game.season == season)
                .where((Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"))
                .where(~Game.nba_game_id.startswith("seed-"))
                .order_by(Game.game_date, Game.nba_game_id)
            )
        )
        .scalars()
        .all()
    )


async def fetch_box_scores(
    db: AsyncSession, *, season: str, output_dir: Path, refresh: bool = False
) -> dict[str, Any]:
    """Fetch resumable per-game box files for already-cached canonical games."""
    games = await _canonical_games(db, season)
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    source = NbaApiDataSource(settings.nba_api, Path("apps/api/app/core/seed"))
    fetched = 0
    reused = 0
    failures: list[dict[str, str]] = []
    for index, game in enumerate(games, start=1):
        target = output_dir / f"{game.nba_game_id}.json"
        if target.exists() and not refresh:
            reused += 1
            continue
        try:
            raw = source.get_game_box_score(game.nba_game_id)
            safe = _json_safe(raw)
            normalized = normalize_box_score(game.nba_game_id, safe)
            document = {
                "nba_game_id": game.nba_game_id,
                "fetched_at": datetime.now(UTC).isoformat(),
                "source": "NBA.com BoxScoreTraditionalV3+BoxScoreSummaryV3",
                "raw_sha256": hashlib.sha256(canonical_json(safe)).hexdigest(),
                "data": normalized,
            }
            temporary = target.with_suffix(".json.tmp")
            temporary.write_bytes(canonical_json(document))
            temporary.replace(target)
            fetched += 1
            print(json.dumps({"box_score": index, "of": len(games), "game": game.nba_game_id}))
        except Exception as exc:  # noqa: BLE001
            failures.append({"nba_game_id": game.nba_game_id, "error": str(exc)})
            print(json.dumps({"box_score_error": game.nba_game_id, "error": str(exc)}))
    return {"games": len(games), "fetched": fetched, "reused": reused, "failures": failures}


def _game_row(game: Game, event_hash: str) -> dict[str, Any]:
    source_game_id = game.source_game_id or game.nba_game_id
    return {
        "nba_game_id": game.nba_game_id,
        "season": game.season,
        "game_date": game.game_date.isoformat(),
        "home_team_id": game.home_team_id,
        "away_team_id": game.away_team_id,
        "home_score": game.home_score,
        "away_score": game.away_score,
        "status": game.status,
        "season_type": game.season_type,
        "data_status": "analysis_ready",
        "source_name": game.source_name or "NbaApiDataSource",
        "source_url": game.source_url
        or (
            "https://stats.nba.com/stats/playbyplayv3"
            f"?GameID={source_game_id}&StartPeriod=0&EndPeriod=14"
        ),
        "source_game_id": source_game_id,
        "source_fetched_at": game.source_fetched_at,
        "source_payload_hash": game.source_payload_hash or event_hash,
        "game_label": game.game_label,
        "series_name": game.series_name,
        "series_game_number": game.series_game_number,
    }


def _event_row(event: GameEvent, nba_game_id: str, nba_player_id: int | None) -> dict[str, Any]:
    return {
        "nba_game_id": nba_game_id,
        "sequence": event.sequence,
        "period": event.period,
        "clock": event.clock,
        "team_id": event.team_id,
        "nba_player_id": nba_player_id,
        "event_type": event.event_type,
        "description": event.description,
        "home_score": event.home_score,
        "away_score": event.away_score,
        "score_margin": event.score_margin,
        "shot_type": event.shot_type,
        "shot_result": event.shot_result,
        "shot_distance_ft": event.shot_distance_ft,
    }


def complete_overtime_period_scores(
    game: Game,
    period_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fill summary-v3's missing overtime columns from cumulative PBP scores."""
    rows = [dict(row) for row in period_rows]
    expected = {
        game.home_team_id: game.home_score,
        game.away_team_id: game.away_score,
    }
    totals = {
        team_id: sum(row["points"] for row in rows if row["team_id"] == team_id)
        for team_id in expected
    }
    if totals == expected:
        return rows
    max_period = max((int(row["period"]) for row in event_rows), default=4)
    for period in range(5, max_period + 1):
        period_events = [row for row in event_rows if int(row["period"]) == period]
        if not period_events:
            continue
        cumulative = {
            game.home_team_id: max(int(row.get("home_score") or 0) for row in period_events),
            game.away_team_id: max(int(row.get("away_score") or 0) for row in period_events),
        }
        for team_id in expected:
            points = cumulative[team_id] - totals[team_id]
            if points < 0:
                raise ValueError(f"{game.nba_game_id}: invalid cumulative overtime score")
            rows.append(
                {
                    "nba_game_id": game.nba_game_id,
                    "team_id": team_id,
                    "period": period,
                    "points": points,
                }
            )
            totals[team_id] += points
    if totals != expected:
        raise ValueError(f"{game.nba_game_id}: overtime period scores do not reconcile")
    return rows


def _draft_report(
    game: Game,
    box: dict[str, Any],
    runs: list[ScoringRun],
    stretches: list[BadStretch],
) -> dict[str, Any]:
    winner = game.home_team_id if game.home_score > game.away_score else game.away_team_id
    loser = game.away_team_id if winner == game.home_team_id else game.home_team_id
    winner_score = max(game.home_score, game.away_score)
    loser_score = min(game.home_score, game.away_score)
    player_rows = box["player_game_stats"]
    leaders = sorted(player_rows, key=lambda row: (-row["points"], row["nba_player_id"]))[:3]
    names = {row["nba_player_id"]: row["full_name"] for row in box["players"]}
    player_notes = [
        f"{names.get(row['nba_player_id'], row['nba_player_id'])}: {row['points']} points, "
        f"{row['rebounds']} rebounds, {row['assists']} assists."
        for row in leaders
    ]
    knicks_runs = sorted(
        (run for run in runs if run.team_id == "NYK"), key=lambda run: -run.score_delta
    )
    opponent_runs = sorted(
        (run for run in runs if run.team_id != "NYK"), key=lambda run: -run.score_delta
    )

    def describe_run(run: ScoringRun | None) -> str:
        if run is None:
            return "No qualifying scoring run was detected in the cached play-by-play."
        return (
            f"{run.team_id} produced a {run.points_for}-{run.points_against} run in Q{run.period} "
            f"from {run.start_clock} to {run.end_clock}."
        )

    worst = min(stretches, key=lambda row: row.score_delta, default=None)
    report = {
        "nba_game_id": game.nba_game_id,
        "report_type": "postgame",
        "title": f"{winner} {winner_score}, {loser} {loser_score}",
        "summary": (
            f"{winner} defeated {loser} {winner_score}-{loser_score} on "
            f"{game.game_date.isoformat()}."
        ),
        "turning_point": describe_run((opponent_runs or knicks_runs or [None])[0]),
        "best_stretch": describe_run(knicks_runs[0] if knicks_runs else None),
        "worst_stretch": (
            f"Q{worst.period} {worst.start_clock}-{worst.end_clock}: {worst.summary}"
            if worst
            else "No qualifying adverse stretch was detected in the cached play-by-play."
        ),
        "player_notes": json.dumps(player_notes, separators=(",", ":")),
        "suggested_adjustments": "[]",
        "sources_json": json.dumps(
            [
                {"type": "game", "nba_game_id": game.nba_game_id},
                {"type": "play_by_play", "nba_game_id": game.nba_game_id},
                {"type": "traditional_box_score", "nba_game_id": game.nba_game_id},
            ],
            separators=(",", ":"),
        ),
        "tool_trace_json": "[]",
    }
    report_hash = hashlib.sha256(canonical_json(report)).hexdigest()
    return {**report, "reviewed": False, "review_hash": report_hash}


async def export_release_candidate(
    db: AsyncSession,
    *,
    season: str,
    version: str,
    box_dir: Path,
    review_manifest: Path | None = None,
) -> dict[str, Any]:
    games = await _canonical_games(db, season)
    if not games:
        raise ValueError(f"No canonical games found for {season}")
    game_ids = [game.id for game in games]
    events = list(
        (
            await db.execute(
                select(GameEvent)
                .where(GameEvent.game_id.in_(game_ids))
                .order_by(GameEvent.game_id, GameEvent.sequence)
            )
        )
        .scalars()
        .all()
    )
    event_player_ids = {event.player_id for event in events if event.player_id is not None}
    event_players = {
        player.id: player
        for player in (
            await db.execute(select(Player).where(Player.id.in_(event_player_ids)))
        ).scalars()
    }
    events_by_game: dict[int, list[GameEvent]] = defaultdict(list)
    for event in events:
        events_by_game[event.game_id].append(event)
    runs_by_game: dict[int, list[ScoringRun]] = defaultdict(list)
    for run in (
        await db.execute(select(ScoringRun).where(ScoringRun.game_id.in_(game_ids)))
    ).scalars():
        runs_by_game[run.game_id].append(run)
    stretches_by_game: dict[int, list[BadStretch]] = defaultdict(list)
    for stretch in (
        await db.execute(select(BadStretch).where(BadStretch.game_id.in_(game_ids)))
    ).scalars():
        stretches_by_game[stretch.game_id].append(stretch)

    approvals: dict[str, str] = {}
    if review_manifest and review_manifest.exists():
        review_data = json.loads(review_manifest.read_text())
        approvals = {
            str(key): str(value) for key, value in review_data.get("approvals", {}).items()
        }

    all_events: list[dict[str, Any]] = []
    game_rows: list[dict[str, Any]] = []
    team_stats: list[dict[str, Any]] = []
    player_stats: list[dict[str, Any]] = []
    period_scores: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    box_players: dict[int, dict[str, Any]] = {}
    review_candidates: dict[str, str] = {}
    missing_boxes: list[str] = []
    for game in games:
        box_path = box_dir / f"{game.nba_game_id}.json"
        if not box_path.exists():
            missing_boxes.append(game.nba_game_id)
            continue
        box_document = json.loads(box_path.read_text())
        box = box_document["data"]
        box_players.update({row["nba_player_id"]: row for row in box["players"]})
        team_stats.extend(box["team_game_stats"])
        player_stats.extend(box["player_game_stats"])
        game_events = [
            _event_row(
                event,
                game.nba_game_id,
                event_players[event.player_id].nba_player_id
                if event.player_id in event_players
                else None,
            )
            for event in events_by_game[game.id]
        ]
        completed_periods = complete_overtime_period_scores(game, box["period_scores"], game_events)
        period_scores.extend(completed_periods)
        all_events.extend(game_events)
        event_hash = hashlib.sha256(canonical_json(game_events)).hexdigest()
        game_rows.append(_game_row(game, event_hash))
        report = _draft_report(game, box, runs_by_game[game.id], stretches_by_game[game.id])
        review_hash = report.pop("review_hash")
        review_candidates[game.nba_game_id] = review_hash
        report["reviewed"] = approvals.get(game.nba_game_id) == review_hash
        reports.append(report)
    if missing_boxes:
        raise ValueError(f"Missing {len(missing_boxes)} box files: {', '.join(missing_boxes[:10])}")

    teams = list((await db.execute(select(Team).order_by(Team.id))).scalars())
    existing_players = {
        player.nba_player_id: player
        for player in (await db.execute(select(Player).order_by(Player.nba_player_id))).scalars()
    }
    player_rows = []
    for nba_player_id in sorted(set(existing_players) | set(box_players)):
        existing = existing_players.get(nba_player_id)
        box_player = box_players.get(nba_player_id, {})
        player_rows.append(
            {
                "nba_player_id": nba_player_id,
                "full_name": existing.full_name if existing else box_player["full_name"],
                "team_id": box_player.get("team_id") or (existing.team_id if existing else None),
                "position": box_player.get("position") or (existing.position if existing else None),
                "jersey_number": box_player.get("jersey_number")
                or (existing.jersey_number if existing else None),
            }
        )
    payload = {
        "manifest": {
            "version": version,
            "season": season,
            "source": "NBA.com cached play-by-play + v3 box scores",
            "expected_games": len(games),
            "expected_game_ids": [game.nba_game_id for game in games],
        },
        "data": {
            "teams": [
                {
                    "id": team.id,
                    "nba_team_id": team.nba_team_id,
                    "name": team.name,
                    "city": team.city,
                    "abbreviation": team.abbreviation,
                    "conference": team.conference,
                    "division": team.division,
                }
                for team in teams
            ],
            "players": player_rows,
            "games": game_rows,
            "events": all_events,
            "period_scores": period_scores,
            "team_game_stats": team_stats,
            "player_game_stats": player_stats,
            "reports": reports,
        },
        "review_manifest": {
            "instructions": (
                "Approve only unchanged reports by copying candidate hashes to approvals."
            ),
            "candidates": review_candidates,
            "approvals": approvals,
        },
    }
    return _json_safe(payload)


def fetch_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    async def run() -> None:
        async with AsyncSessionLocal() as db:
            result = await fetch_box_scores(
                db, season=args.season, output_dir=args.out_dir, refresh=args.refresh
            )
            print(json.dumps(result, sort_keys=True))
            if result["failures"]:
                raise SystemExit(1)

    asyncio.run(run())


def export_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--version", required=True)
    parser.add_argument("--box-dir", type=Path, required=True)
    parser.add_argument("--review-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    async def run() -> None:
        async with AsyncSessionLocal() as db:
            payload = await export_release_candidate(
                db,
                season=args.season,
                version=args.version,
                box_dir=args.box_dir,
                review_manifest=args.review_manifest,
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_json(payload))
        reviewed = sum(1 for report in payload["data"]["reports"] if report["reviewed"])
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "games": len(payload["data"]["games"]),
                    "events": len(payload["data"]["events"]),
                    "reviewed_reports": reviewed,
                },
                sort_keys=True,
            )
        )

    asyncio.run(run())


def review_pack_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--approvals", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.candidate.read_text())
    reports = payload["data"]["reports"]
    games = {row["nba_game_id"]: row for row in payload["data"]["games"]}
    candidates = payload["review_manifest"]["candidates"]
    lines = [
        f"# KnicksIQ {payload['manifest']['version']} report review",
        "",
        "Approve a report only after checking every score, player line, run, and citation source.",
        (
            "Copy its immutable candidate hash into the approvals JSON; "
            "never approve by game ID alone."
        ),
        "",
    ]
    for report in reports:
        game_id = report["nba_game_id"]
        game = games[game_id]
        notes = json.loads(report["player_notes"])
        lines.extend(
            [
                f"## [ ] {game['game_date']} · {game['away_team_id']} at {game['home_team_id']}",
                "",
                f"- NBA game ID: `{game_id}`",
                f"- Candidate hash: `{candidates[game_id]}`",
                f"- Final: {game['away_team_id']} {game['away_score']}, "
                f"{game['home_team_id']} {game['home_score']}",
                f"- Title: {report['title']}",
                f"- Summary: {report['summary']}",
                f"- Turning point: {report['turning_point']}",
                f"- Best stretch: {report['best_stretch']}",
                f"- Worst stretch: {report['worst_stretch']}",
                "- Player notes:",
                *[f"  - {note}" for note in notes],
                "",
            ]
        )
    approval_template = {
        "version": payload["manifest"]["version"],
        "instructions": (
            "After manual review, copy approved candidate hashes from the review pack here."
        ),
        "approvals": {},
    }
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.approvals.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text("\n".join(lines))
    args.approvals.write_bytes(canonical_json(approval_template))
    print(
        json.dumps(
            {
                "reports": len(reports),
                "markdown": str(args.markdown),
                "approvals": str(args.approvals),
            },
            sort_keys=True,
        )
    )
