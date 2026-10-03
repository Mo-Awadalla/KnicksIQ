"""Import independently verified scoring comparisons without changing canonical rows.

The caller supplies trusted evidence digests, never digests inferred from an
untrusted import. Runtime units require both intact proof and its SQL snapshot.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.comparison_source import ComparisonSource
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
from app.services.release_bundle import canonical_json, read_bundle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MODELS = {
    "events": GameEvent,
    "period_scores": PeriodScore,
    "player_game_stats": PlayerGameStat,
    "team_game_stats": TeamGameStat,
}
EXCLUDED = {"id", "release_id", "game_id", "nba_game_id", "created_at", "updated_at", "player_id"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _scalar(value: Any) -> Any:
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        ).isoformat()
    return value.isoformat() if isinstance(value, date) else value


def _boundary(start: dict, end: dict) -> dict:
    return {
        "start_source": start["source"],
        "start_source_state": start["edge"],
        "end_source": end["source"],
        "end_source_state": end["edge"],
        "start_margin": start["margin"],
        "end_margin": end["margin"],
    }


def _largest(rows: list[tuple[int, dict]]) -> dict:
    value = max((v for v, _ in rows), default=None)
    boundaries = [b for v, b in rows if v == value]
    return {
        "value": value,
        "boundaries": sorted(boundaries, key=lambda b: json.dumps(b, sort_keys=True)),
    }


def _independent_measures(record: dict) -> dict:
    """Reference check uses exhaustive intervals, not the producer's prefix/suffix folds."""
    events, identity = record["events"], record["nba_game_id"]
    _require(bool(events), "Missing verified event population")
    side = "home" if record["home_team_id"] == "NYK" else "away"
    other = "away" if side == "home" else "home"
    score = {"home": 0, "away": 0}
    states = [{"source": events[0]["canonical_id"], "edge": "before", "margin": 0}]
    scoring = []
    for seq, event in enumerate(events, 1):
        _require(
            event["sequence"] == seq and event["canonical_id"] == f"event:{identity}:{seq}",
            "Invalid canonical trajectory order",
        )
        points = event["points"]
        _require(
            type(points) is int and 0 <= points <= 3 and event["score_before"] == score,
            "Invalid verified scoring contribution",
        )
        if points:
            team = event["team_id"]
            _require(
                team in {record["home_team_id"], record["away_team_id"]}, "Foreign scoring actor"
            )
            score["home" if team == record["home_team_id"] else "away"] += points
            scoring.append(event)
            states.append(
                {
                    "source": event["canonical_id"],
                    "edge": "after",
                    "margin": score[side] - score[other],
                }
            )
        _require(event["score_after"] == score, "Inconsistent verified scoring states")
    candidates: dict[str, list] = defaultdict(list)
    for index, start in enumerate(states):
        future = states[index + 1 :]
        margin = start["margin"]
        if margin < 0:
            candidates["largest_observed_deficit"].append(
                (-margin, {"source": start["source"], "margin": margin})
            )
            for key, predicate in (
                ("largest_deficit_later_tied", lambda m: m >= 0),
                ("largest_deficit_later_led", lambda m: m > 0),
            ):
                recovery = next((s for s in future if predicate(s["margin"])), None)
                if recovery is not None:
                    candidates[key].append((-margin, _boundary(start, recovery)))
            if states[-1]["margin"] > 0:
                candidates["largest_deficit_in_eventual_win"].append(
                    (-margin, _boundary(start, states[-1]))
                )
        if margin > 0:
            surrender = next((s for s in future if s["margin"] <= 0), None)
            if surrender is not None:
                candidates["largest_positive_lead_surrendered"].append(
                    (margin, _boundary(start, surrender))
                )
                if states[-1]["margin"] < 0:
                    candidates["largest_positive_lead_surrendered_in_final_loss"].append(
                        (margin, _boundary(start, surrender))
                    )
        for end in future:
            gain = end["margin"] - margin
            if gain > 0:
                candidates["knicks_largest_unrestricted_net_gain"].append(
                    (gain, _boundary(start, end))
                )
            if gain < 0:
                candidates["largest_unrestricted_margin_decline"].append(
                    (-gain, _boundary(start, end))
                )
    offset = 0
    for team, group in itertools.groupby(scoring, key=lambda e: e["team_id"]):
        run = list(group)
        boundary = {
            **_boundary(states[offset], states[offset + len(run)]),
            "scoring_sources": [e["canonical_id"] for e in run],
        }
        key = (
            "knicks_largest_unanswered_run" if team == "NYK" else "opponent_largest_unanswered_run"
        )
        candidates[key].append((sum(e["points"] for e in run), boundary))
        offset += len(run)
    keys = (
        "largest_observed_deficit",
        "largest_deficit_later_tied",
        "largest_deficit_later_led",
        "largest_deficit_in_eventual_win",
        "knicks_largest_unanswered_run",
        "opponent_largest_unanswered_run",
        "knicks_largest_unrestricted_net_gain",
        "largest_unrestricted_margin_decline",
        "largest_positive_lead_surrendered",
        "largest_positive_lead_surrendered_in_final_loss",
    )
    result = {key: _largest(candidates[key]) for key in keys}
    q3 = [r for r in record["period_receipts"] if r["canonical_id"].endswith(":3")]
    _require(len(q3) == 2, "Missing verified Q3 pair")
    nyk = next(r["points"] for r in q3 if r["canonical_id"] == f"period:{identity}:NYK:3")
    opponent = next(r["points"] for r in q3 if r["canonical_id"] != f"period:{identity}:NYK:3")
    boundary = {"period_sources": sorted(r["canonical_id"] for r in q3)}
    result["q3_fewest_points"] = {"value": nyk, "boundaries": [boundary]}
    result["q3_worst_margin"] = {"value": nyk - opponent, "boundaries": [boundary]}
    return result


async def _sql_snapshot(
    db: AsyncSession, release_id: int, spec: dict, game_ids: set[int] | None = None
) -> dict:
    game_fields = spec["fields"]["games"]
    stmt = select(Game.id, Game.nba_game_id, *(getattr(Game, f) for f in game_fields)).where(
        Game.release_id == release_id
    )
    if game_ids is not None:
        stmt = stmt.where(Game.id.in_(game_ids))
    rows = (await db.execute(stmt.order_by(Game.nba_game_id))).all()
    games = {r[0]: r[1] for r in rows}
    snapshots = {r[1]: {"games": [[_scalar(v) for v in r[2:]]]} for r in rows}
    for collection, model in MODELS.items():
        fields = spec["fields"][collection]
        selected = [getattr(model, f) for f in fields if f != "nba_player_id"]
        stmt = select(model.game_id, *selected).where(model.game_id.in_(games))
        if "nba_player_id" in fields:
            stmt = (
                select(model.game_id, *selected, Player.nba_player_id)
                .outerjoin(Player, model.player_id == Player.id)
                .where(model.game_id.in_(games))
            )
        for snapshot in snapshots.values():
            snapshot[collection] = []
        for row in (await db.execute(stmt)).all():
            values = dict(
                zip(
                    [f for f in fields if f != "nba_player_id"],
                    row[1 : 1 + len(selected)],
                    strict=True,
                )
            )
            if "nba_player_id" in fields:
                values["nba_player_id"] = row[-1]
            snapshots[games[row[0]]][collection].append([_scalar(values[f]) for f in fields])
    for snapshot in snapshots.values():
        for collection in MODELS:
            snapshot[collection].sort(key=canonical_json)
    return {identity: _digest(snapshot) for identity, snapshot in snapshots.items()}


def _archive_bindings(data: dict, known_players: set[int]) -> dict:
    fields = {"games": sorted(set().union(*(set(g) for g in data["games"])) - EXCLUDED)}
    for collection in MODELS:
        fields[collection] = sorted(set().union(*(set(r) for r in data[collection])) - EXCLUDED)
    grouped = {g["nba_game_id"]: {"games": []} for g in data["games"]}
    for collection, names in fields.items():
        for snapshot in grouped.values():
            snapshot.setdefault(collection, [])
        for row in data[collection]:
            values = []
            for key in names:
                value = row.get(key)
                if key == "nba_player_id" and value not in known_players:
                    value = None
                if key == "source_fetched_at" and value is not None:
                    value = _scalar(datetime.fromisoformat(value))
                values.append(value)
            grouped[row["nba_game_id"]][collection].append(values)
    for snapshot in grouped.values():
        for collection in MODELS:
            snapshot[collection].sort(key=canonical_json)
    return {
        "fields": fields,
        "by_game": {identity: _digest(snapshot) for identity, snapshot in grouped.items()},
    }


def _facts(record: dict, compared: dict) -> dict:
    used = set()
    for measure in compared["measures"].values():
        for boundary in measure["boundaries"]:
            used.update(boundary.get("scoring_sources", []))
            used.update(
                boundary[k] for k in ("source", "start_source", "end_source") if k in boundary
            )
    events = {
        e["canonical_id"]: {
            k: e[k]
            for k in (
                "canonical_id",
                "sequence",
                "period",
                "clock",
                "team_id",
                "nba_player_id",
                "points",
                "score_before",
                "score_after",
                "primary_action_sha256",
            )
        }
        for e in record["events"]
        if e["canonical_id"] in used
    }
    _require(set(events) == used, "Comparison names an unsupported event boundary")
    return {
        "events": events,
        "periods": record["period_receipts"],
        "primary_capture_sha256": record["primary_capture_sha256"],
    }


async def import_comparison_source(
    db: AsyncSession,
    *,
    bundle: Path,
    trajectories: Path,
    source_review: Path,
    comparisons: Path,
    expected_hashes: dict[str, str],
) -> ComparisonSource:
    paths = {
        "bundle": bundle,
        "trajectories": trajectories,
        "source_review": source_review,
        "comparisons": comparisons,
    }
    _require(
        set(expected_hashes) == set(paths), "Every input requires an independently supplied digest"
    )
    raw = {name: path.read_bytes() for name, path in paths.items()}
    _require(
        all(
            hashlib.sha256(value).hexdigest() == expected_hashes[name]
            for name, value in raw.items()
        ),
        "Pinned comparison import bytes changed",
    )
    archive = read_bundle(bundle, expected_hashes["bundle"])
    report, review = json.loads(raw["comparisons"]), json.loads(raw["source_review"])
    version = archive["manifest"]["version"]
    release = (
        await db.execute(select(DatasetRelease).where(DatasetRelease.version == version))
    ).scalar_one_or_none()
    _require(
        release is not None
        and release.validation_passed
        and release.manifest_sha256 == expected_hashes["bundle"],
        "SQL release does not match the validated source bundle",
    )
    assert release is not None
    _require(
        report["status"] == "COMPLETE_PINNED_MEASURE_COMPARISONS"
        and review["status"] == "PER_ACTION_SCORING_SOURCE_VERIFIED"
        and report["data_version"] == review["data_version"] == version
        and report["trajectories_sha256"]
        == review["trajectories_sha256"]
        == expected_hashes["trajectories"]
        and report["source_review_sha256"] == expected_hashes["source_review"]
        and review["bundle_sha256"] == expected_hashes["bundle"]
        and report["metric_defaults"] is None
        and report["gold_approved"] is False
        and report["frozen"] is False
        and report["ranked_receipts_created"] is False,
        "Foreign or unverified comparison lineage",
    )
    records = [json.loads(line) for line in raw["trajectories"].splitlines()]
    games = {g["nba_game_id"]: g for g in archive["data"]["games"]}
    compared = {g["nba_game_id"]: g for g in report["games"]}
    sources = {g["nba_game_id"]: g for g in review["sources"]}
    _require(
        len(records) == len(games) == len(compared) == len(sources)
        and len({r["nba_game_id"] for r in records}) == len(records)
        and set(games) == set(compared) == set(sources),
        "Incomplete or duplicate comparison population",
    )
    archive_events = {(e["nba_game_id"], e["sequence"]): e for e in archive["data"]["events"]}
    archive_periods = {
        f"period:{r['nba_game_id']}:{r['team_id']}:{r['period']}": r
        for r in archive["data"]["period_scores"]
    }
    facts = {}
    for record in records:
        identity = record["nba_game_id"]
        game = games[identity]
        _require(
            record["recipe"] == "nba-action-scoring-trajectory-v1"
            and record["data_version"] == version
            and record["primary_capture_sha256"] == sources[identity]["primary_capture_sha256"]
            and all(
                record[k] == game[k]
                for k in ("season", "season_type", "game_date", "home_team_id", "away_team_id")
            ),
            "Foreign trajectory recipe, capture or game metadata",
        )
        expected_header = {
            "nba_game_id": identity,
            "game_source": f"game:{identity}",
            "source_document_id": record["source_document_id"],
            **{k: game[k] for k in ("season", "season_type", "game_date")},
            "final_nyk_margin": (game["home_score"] - game["away_score"])
            * (1 if game["home_team_id"] == "NYK" else -1),
        }
        _require(
            {k: v for k, v in compared[identity].items() if k != "measures"} == expected_header,
            "Comparison contains unsupported game metadata or final margin",
        )
        expected_periods = {
            key: {"canonical_id": key, "points": row["points"], "row_sha256": _digest(row)}
            for key, row in archive_periods.items()
            if row["nba_game_id"] == identity
        }
        actual_periods = {r["canonical_id"]: r for r in record["period_receipts"]}
        _require(
            len(actual_periods) == len(record["period_receipts"])
            and actual_periods == expected_periods,
            "Trajectory period receipts do not represent the complete source archive",
        )
        _require(
            record["game_row_sha256"] == _digest(games[identity])
            and record["source_document_id"] == sources[identity]["source_document_id"]
            and record["source_document_id"]
            == "derived-score-trajectory:"
            + _digest({k: v for k, v in record.items() if k != "source_document_id"}),
            "Changed verified game/source identity",
        )
        for event in record["events"]:
            _require(
                event["canonical_row_sha256"]
                == _digest(archive_events[(identity, event["sequence"])]),
                "Trajectory does not represent the source archive event",
            )
        independently_checked = _independent_measures(record)
        _require(
            compared[identity]["measures"] == independently_checked
            and set(report["definitions"]) == set(independently_checked),
            "Comparison disagrees with independent exhaustive measure check",
        )
        facts[identity] = _facts(record, compared[identity])
    _require(
        sum(len(r["events"]) for r in records) == len(archive_events),
        "Incomplete archive event coverage",
    )
    _require(
        set(report["populations"]) == {"complete_archive", "regular_season", "postseason"},
        "Missing or foreign comparison population",
    )
    for name, population in report["populations"].items():
        subset = [
            g
            for g in report["games"]
            if name == "complete_archive"
            or (name == "regular_season" and g["season_type"] == "regular")
            or (name == "postseason" and g["season_type"] in {"play_in", "playoffs"})
        ]
        _require(
            population["game_count"] == len(subset)
            and population["game_sources"] == sorted(g["game_source"] for g in subset),
            "Incomplete comparison scope",
        )
        for key in report["definitions"]:
            applicable = [g for g in subset if g["measures"][key]["value"] is not None]
            value = (min if key.startswith("q3_") else max)(
                (g["measures"][key]["value"] for g in applicable), default=None
            )
            tied = [g for g in applicable if g["measures"][key]["value"] == value]
            expected = {
                "value": value,
                "game_sources": sorted(g["game_source"] for g in tied),
                "boundaries": [
                    {
                        "game_source": g["game_source"],
                        "source_document_id": g["source_document_id"],
                        **b,
                    }
                    for g in tied
                    for b in g["measures"][key]["boundaries"]
                ],
            }
            _require(
                population["extrema"][key] == expected, "Incorrect or incomplete population extrema"
            )
    known_players = set((await db.execute(select(Player.nba_player_id))).scalars())
    bindings = _archive_bindings(archive["data"], known_players)
    _require(
        await _sql_snapshot(db, release.id, bindings) == bindings["by_game"],
        "SQL archive does not match the complete source projection",
    )
    values = {
        "source_sha256": expected_hashes["comparisons"],
        "bundle_sha256": expected_hashes["bundle"],
        "source_review_sha256": expected_hashes["source_review"],
        "trajectories_sha256": expected_hashes["trajectories"],
        "comparison_json": raw["comparisons"].decode(),
        "facts_json": canonical_json(facts).decode(),
        "facts_sha256": _digest(facts),
        "bindings_json": canonical_json(bindings).decode(),
        "bindings_sha256": _digest(bindings),
    }
    existing = await db.get(ComparisonSource, release.id)
    if existing is not None:
        _require(
            all(getattr(existing, key) == value for key, value in values.items()),
            "An immutable comparison import already exists with different proof",
        )
        return existing
    source = ComparisonSource(release_id=release.id, **values)
    db.add(source)
    await db.commit()
    return source


async def verified_comparison_source(
    db: AsyncSession, release: DatasetRelease, games: list[Game]
) -> tuple[ComparisonSource, dict, dict] | None:
    source = await db.get(ComparisonSource, release.id)
    if source is None:
        return None
    _require(
        source.bundle_sha256 == release.manifest_sha256 and release.validation_passed,
        "Foreign comparison source release",
    )
    _require(
        hashlib.sha256(source.comparison_json.encode()).hexdigest() == source.source_sha256,
        "Stored comparison proof changed",
    )
    report, facts, bindings = (
        json.loads(source.comparison_json),
        json.loads(source.facts_json),
        json.loads(source.bindings_json),
    )
    _require(
        _digest(facts) == source.facts_sha256 and _digest(bindings) == source.bindings_sha256,
        "Stored comparison facts or bindings changed",
    )
    expected = {g.nba_game_id: bindings["by_game"][g.nba_game_id] for g in games}
    _require(
        await _sql_snapshot(db, release.id, bindings, {g.id for g in games}) == expected,
        "Canonical SQL snapshot changed after comparison verification",
    )
    return source, report, facts
