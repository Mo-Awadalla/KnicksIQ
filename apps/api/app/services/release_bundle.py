"""Deterministic release bundles and transactional database loading."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.generated_stat_fact import GeneratedStatFact
from app.models.player import Player
from app.models.report import Report
from app.models.team import Team
from basketball_core.analytics import FactCandidate, build_fact_catalog, fact_fingerprint
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class ReleaseValidationError(ValueError):
    """Raised before any invalid release can be staged or activated."""


@dataclass(frozen=True)
class ReleaseLoadResult:
    release_id: int
    version: str
    inserted: bool
    activated: bool
    games: int


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def build_bundle(payload: dict[str, Any], output: Path) -> str:
    """Write byte-for-byte reproducible gzip JSON and return its SHA-256."""
    data = dict(payload)
    manifest = dict(data.get("manifest") or {})
    content = dict(data.get("data") or {})
    content.setdefault(
        "generated_stat_facts",
        build_fact_catalog(
            list(content.get("games") or []),
            list(content.get("player_game_stats") or []),
            list(content.get("players") or []),
        ),
    )
    data["data"] = content
    manifest["schedule_sha256"] = _schedule_sha256(content.get("games") or [])
    manifest["content_sha256"] = hashlib.sha256(canonical_json(content)).hexdigest()
    data["manifest"] = manifest
    raw = canonical_json(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
            compressed.write(raw)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def _schedule_sha256(games: list[dict[str, Any]]) -> str:
    schedule = [
        {
            key: game.get(key)
            for key in (
                "nba_game_id",
                "season",
                "game_date",
                "home_team_id",
                "away_team_id",
                "home_score",
                "away_score",
                "status",
                "season_type",
            )
        }
        for game in games
    ]
    return hashlib.sha256(canonical_json(schedule)).hexdigest()


def read_bundle(path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    compressed = path.read_bytes()
    actual = hashlib.sha256(compressed).hexdigest()
    if expected_sha256 and actual != expected_sha256:
        raise ReleaseValidationError("Release bundle SHA-256 does not match")
    value = json.loads(gzip.decompress(compressed))
    content = value.get("data") or {}
    expected_content = value.get("manifest", {}).get("content_sha256")
    actual_content = hashlib.sha256(canonical_json(content)).hexdigest()
    if not expected_content or expected_content != actual_content:
        raise ReleaseValidationError("Release content manifest does not match")
    value["bundle_sha256"] = actual
    return value


def validate_bundle(
    bundle: dict[str, Any], *, require_reviewed_reports: bool = True
) -> dict[str, Any]:
    manifest = bundle.get("manifest") or {}
    content = bundle.get("data") or {}
    games = list(content.get("games") or [])
    reports = list(content.get("reports") or [])
    events = list(content.get("events") or [])
    team_stats = list(content.get("team_game_stats") or [])
    player_stats = list(content.get("player_game_stats") or [])
    periods = list(content.get("period_scores") or [])
    generated_facts = list(content.get("generated_stat_facts") or [])
    errors: list[str] = []

    required_manifest = {
        "version",
        "season",
        "source",
        "expected_games",
        "expected_game_ids",
        "schedule_sha256",
        "content_sha256",
    }
    missing = sorted(required_manifest - set(manifest))
    if missing:
        errors.append(f"manifest missing: {', '.join(missing)}")
    game_ids = [str(row.get("nba_game_id") or "") for row in games]
    if len(game_ids) != len(set(game_ids)) or "" in game_ids:
        errors.append("each game must have one unique nba_game_id")
    if len(games) != int(manifest.get("expected_games") or -1):
        errors.append("game count does not match expected_games")
    expected_game_ids = {str(value) for value in manifest.get("expected_game_ids") or []}
    if set(game_ids) != expected_game_ids:
        errors.append("game IDs do not match the LeagueGameFinder schedule manifest")
    if manifest.get("schedule_sha256") != _schedule_sha256(games):
        errors.append("game dates, opponents, scores, or season types do not match the manifest")

    known_players = {int(row.get("nba_player_id") or 0) for row in content.get("players") or []}
    fact_fingerprints: set[str] = set()
    for fact in generated_facts:
        fingerprint = str(fact.get("fingerprint") or "")
        if len(fingerprint) != 64 or fingerprint in fact_fingerprints:
            errors.append("generated facts require unique stable fingerprints")
        fact_fingerprints.add(fingerprint)
        expected_fingerprint = fact_fingerprint(
            FactCandidate(
                fact_type=str(fact.get("fact_type") or ""),
                player_ids=tuple(int(value) for value in fact.get("player_ids") or []),
                stat_keys=tuple(str(value) for value in fact.get("stat_keys") or []),
                timeframe=dict(fact.get("timeframe") or {}),
                statement=str(fact.get("statement") or ""),
                result=dict(fact.get("result") or {}),
                source_game_ids=tuple(fact.get("source_game_ids") or []),
                sample_size=int(fact.get("sample_size") or 0),
                components={},
            ),
            str(fact.get("detector_version") or ""),
        )
        if fingerprint != expected_fingerprint:
            errors.append(f"{fingerprint}: generated fact fingerprint does not reconcile")
        if not set(int(value) for value in fact.get("player_ids") or []).issubset(known_players):
            errors.append(f"{fingerprint}: generated fact references an unknown player")
        if not set(str(value) for value in fact.get("source_game_ids") or []).issubset(
            set(game_ids)
        ):
            errors.append(f"{fingerprint}: generated fact references an unknown game")
        components = fact.get("score_components") or {}
        component_names = {
            "magnitude",
            "rarity",
            "sample_quality",
            "recency",
            "coverage",
            "basketball_relevance",
            "novelty",
            "interpretability",
        }
        if not component_names.issubset(components):
            errors.append(f"{fingerprint}: generated fact score components are incomplete")
        recomputed = sum(float(components.get(name) or 0) for name in component_names) - float(
            components.get("penalty") or 0
        )
        if abs(max(0.0, recomputed) - float(fact.get("total_score") or 0)) > 0.00001:
            errors.append(f"{fingerprint}: generated fact total score does not reconcile")
        if not fact.get("detector_version") or not fact.get("statement"):
            errors.append(f"{fingerprint}: generated fact metadata is incomplete")
        if str(fact.get("data_through") or "") > max(
            (str(game.get("game_date")) for game in games), default=""
        ):
            errors.append(f"{fingerprint}: generated fact data-through exceeds release coverage")

    all_reports_by_game: dict[str, list[dict[str, Any]]] = {}
    reports_by_game: dict[str, list[dict[str, Any]]] = {}
    for row in reports:
        all_reports_by_game.setdefault(str(row.get("nba_game_id")), []).append(row)
        if row.get("reviewed"):
            reports_by_game.setdefault(str(row.get("nba_game_id")), []).append(row)
    events_by_game: dict[str, list[dict[str, Any]]] = {}
    for row in events:
        events_by_game.setdefault(str(row.get("nba_game_id")), []).append(row)
    team_by_game: dict[str, list[dict[str, Any]]] = {}
    for row in team_stats:
        team_by_game.setdefault(str(row.get("nba_game_id")), []).append(row)
    players_by_game: dict[str, list[dict[str, Any]]] = {}
    for row in player_stats:
        players_by_game.setdefault(str(row.get("nba_game_id")), []).append(row)
    periods_by_game: dict[str, list[dict[str, Any]]] = {}
    for row in periods:
        periods_by_game.setdefault(str(row.get("nba_game_id")), []).append(row)

    for game in games:
        game_id = str(game["nba_game_id"])
        teams = {game.get("home_team_id"), game.get("away_team_id")}
        if "NYK" not in teams:
            errors.append(f"{game_id}: not a Knicks game")
        if game.get("season") != manifest.get("season"):
            errors.append(f"{game_id}: season does not match release manifest")
        if game.get("status") != "final" or not all(
            game.get(field)
            for field in (
                "source_name",
                "source_url",
                "source_game_id",
                "source_fetched_at",
                "source_payload_hash",
            )
        ):
            errors.append(f"{game_id}: incomplete final/source metadata")
        game_events = events_by_game.get(game_id, [])
        if not game_events:
            errors.append(f"{game_id}: no usable play-by-play")
        else:
            reaches_final = any(
                int(row.get("home_score") or 0) == int(game.get("home_score") or 0)
                and int(row.get("away_score") or 0) == int(game.get("away_score") or 0)
                for row in game_events
            )
            if not reaches_final:
                errors.append(f"{game_id}: play-by-play final score does not reconcile")
        if require_reviewed_reports:
            if len(reports_by_game.get(game_id, [])) != 1:
                errors.append(f"{game_id}: requires exactly one reviewed report")
        elif len(all_reports_by_game.get(game_id, [])) != 1:
            errors.append(f"{game_id}: requires exactly one report draft")
        game_team_stats = team_by_game.get(game_id, [])
        if len(game_team_stats) != 2 or {row.get("team_id") for row in game_team_stats} != teams:
            errors.append(f"{game_id}: incomplete team box score")
        if {row.get("team_id") for row in players_by_game.get(game_id, [])} != teams:
            errors.append(f"{game_id}: missing player box score")
        for team_id in teams:
            team_player_rows = [
                row for row in players_by_game.get(game_id, []) if row.get("team_id") == team_id
            ]
            if team_player_rows and not any(
                float(row.get("minutes") or 0) > 0 for row in team_player_rows
            ):
                errors.append(f"{game_id}: {team_id} player minutes are missing")
        game_periods = periods_by_game.get(game_id, [])
        if {row.get("team_id") for row in game_periods} != teams:
            errors.append(f"{game_id}: incomplete period scores")
        for team_id, expected in (
            (game.get("home_team_id"), game.get("home_score")),
            (game.get("away_team_id"), game.get("away_score")),
        ):
            period_total = sum(
                int(row.get("points") or 0) for row in game_periods if row.get("team_id") == team_id
            )
            team_total = next(
                (
                    int(row.get("points") or 0)
                    for row in game_team_stats
                    if row.get("team_id") == team_id
                ),
                -1,
            )
            if period_total != expected or team_total != expected:
                errors.append(f"{game_id}: {team_id} score totals do not reconcile")
            team_row = next((row for row in game_team_stats if row.get("team_id") == team_id), {})
            for category in (
                "points",
                "field_goals_made",
                "field_goals_attempted",
                "three_pointers_made",
                "three_pointers_attempted",
                "free_throws_made",
                "free_throws_attempted",
                "offensive_rebounds",
                "defensive_rebounds",
                "rebounds",
                "assists",
                "steals",
                "blocks",
                "turnovers",
                "personal_fouls",
            ):
                player_total = sum(
                    int(row.get(category) or 0)
                    for row in players_by_game.get(game_id, [])
                    if row.get("team_id") == team_id
                )
                if player_total != int(team_row.get(category) or 0):
                    errors.append(f"{game_id}: {team_id} player {category} do not reconcile")

    result = {"passed": not errors, "errors": errors, "games": len(games)}
    if errors:
        raise ReleaseValidationError("; ".join(errors[:20]))
    return result


async def load_release_bundle(
    db: AsyncSession,
    path: Path,
    *,
    expected_sha256: str | None = None,
    activate: bool = False,
) -> ReleaseLoadResult:
    """Load a release atomically; repeated loads of the same version are no-ops."""
    bundle = read_bundle(path, expected_sha256)
    validation = validate_bundle(bundle)
    manifest = bundle["manifest"]
    existing = (
        await db.execute(
            select(DatasetRelease).where(DatasetRelease.version == manifest["version"])
        )
    ).scalar_one_or_none()
    if existing:
        if existing.manifest_sha256 != bundle["bundle_sha256"]:
            raise ReleaseValidationError("Version already exists with a different manifest")
        if activate and existing.status != "active":
            await db.execute(
                update(DatasetRelease)
                .where(DatasetRelease.status == "active")
                .where(DatasetRelease.id != existing.id)
                .values(status="superseded")
            )
            existing.status = "active"
            existing.activated_at = datetime.now(UTC)
            await db.commit()
        return ReleaseLoadResult(
            existing.id, existing.version, False, existing.status == "active", validation["games"]
        )

    release = DatasetRelease(
        version=manifest["version"],
        season=manifest["season"],
        source=manifest["source"],
        manifest_sha256=bundle["bundle_sha256"],
        manifest_json=json.dumps(manifest, sort_keys=True),
        validation_json=json.dumps(validation, sort_keys=True),
        validation_passed=True,
        status="staged",
    )
    db.add(release)
    await db.flush()
    content = bundle["data"]

    for row in content.get("teams", []):
        if await db.get(Team, row["id"]) is None:
            db.add(Team(**row))
    for row in content.get("players", []):
        found = (
            await db.execute(select(Player).where(Player.nba_player_id == row["nba_player_id"]))
        ).scalar_one_or_none()
        if found is None:
            db.add(Player(**row))
    await db.flush()
    players = {
        player.nba_player_id: player.id
        for player in (await db.execute(select(Player))).scalars().all()
    }
    games: dict[str, Game] = {}
    for raw in content["games"]:
        row = dict(raw)
        row["game_date"] = date.fromisoformat(row["game_date"])
        if isinstance(row.get("source_fetched_at"), str):
            row["source_fetched_at"] = datetime.fromisoformat(row["source_fetched_at"])
        row["release_id"] = release.id
        game = Game(**row)
        db.add(game)
        await db.flush()
        games[game.nba_game_id] = game
    for raw in content.get("events", []):
        row = dict(raw)
        game = games[row.pop("nba_game_id")]
        nba_player_id = row.pop("nba_player_id", None)
        row["game_id"] = game.id
        row["player_id"] = players.get(nba_player_id)
        db.add(GameEvent(**row))
    for model, key in (
        (PeriodScore, "period_scores"),
        (TeamGameStat, "team_game_stats"),
        (PlayerGameStat, "player_game_stats"),
    ):
        for raw in content.get(key, []):
            row = dict(raw)
            row["game_id"] = games[row.pop("nba_game_id")].id
            row["release_id"] = release.id
            if model is PlayerGameStat:
                row["player_id"] = players[row.pop("nba_player_id")]
            db.add(model(**row))
    for raw in content.get("reports", []):
        row = dict(raw)
        game = games[row.pop("nba_game_id")]
        row["game_id"] = game.id
        row["release_id"] = release.id
        report_content = canonical_json(row)
        row["content_sha256"] = hashlib.sha256(report_content).hexdigest()
        db.add(Report(**row))
    for raw in content.get("generated_stat_facts", []):
        row = dict(raw)
        row["release_id"] = release.id
        row["player_ids_json"] = json.dumps(row.pop("player_ids"), sort_keys=True)
        row["stat_keys_json"] = json.dumps(row.pop("stat_keys"), sort_keys=True)
        row["timeframe_json"] = json.dumps(row.pop("timeframe"), sort_keys=True)
        row["result_json"] = json.dumps(row.pop("result"), sort_keys=True)
        row["source_game_ids_json"] = json.dumps(row.pop("source_game_ids"), sort_keys=True)
        row["score_components_json"] = json.dumps(row.pop("score_components"), sort_keys=True)
        if isinstance(row.get("data_through"), str):
            row["data_through"] = date.fromisoformat(row["data_through"])
        db.add(GeneratedStatFact(**row))

    if activate:
        await db.execute(
            update(DatasetRelease)
            .where(DatasetRelease.status == "active")
            .values(status="superseded")
        )
        release.status = "active"
        release.activated_at = datetime.now(UTC)
    await db.commit()
    return ReleaseLoadResult(release.id, release.version, True, activate, len(games))
