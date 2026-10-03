"""Complete, deterministic source units; no evaluation inputs or model calls."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.comparison_sources import verified_comparison_source
from app.services.query_resolution import _CURATED_PLAYER_ALIASES, _player_aliases
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

UNIT_RECIPE = "archive-source-units-v1"


def _record(payload: dict[str, Any], text: str) -> dict[str, Any]:
    payload = {"recipe": UNIT_RECIPE, **payload, "text": text, "semantic_summary": text}
    identity = (
        "archive-unit:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return {"id": identity, "payload": {**payload, "source_document_id": identity}}


def opponent_unit(games: list[Game], opponent: str, version: str) -> dict[str, Any]:
    games = sorted(games, key=lambda g: (g.game_date, g.nba_game_id))
    rows = [
        {
            "game_id": g.id,
            "nba_game_id": g.nba_game_id,
            "game_date": g.game_date.isoformat(),
            "season": g.season,
            "season_type": g.season_type,
            "home_team_id": g.home_team_id,
            "away_team_id": g.away_team_id,
            "home_score": g.home_score,
            "away_score": g.away_score,
            "status": g.status,
            "source_payload_hash": g.source_payload_hash,
        }
        for g in games
    ]
    results = [
        "W" if (r["home_score"] > r["away_score"]) == (r["home_team_id"] == "NYK") else "L"
        for r in rows
    ]
    text = (
        f"Knicks NYK results against {opponent} in the {games[0].season} archive: "
        f"{results.count('W')} wins, {results.count('L')} losses in {len(rows)} final games. "
        "Complete opponent population, including every available phase.\n"
    ) + "\n".join(
        f"{r['nba_game_id']} | {r['game_date']} | {r['season_type']} | "
        f"{r['away_team_id']} {r['away_score']} at {r['home_team_id']} {r['home_score']} | "
        f"Knicks {result}"
        for r, result in zip(rows, results, strict=True)
    )
    return _record(
        {
            "unit_type": "multigame_aggregate",
            "aggregate_kind": "opponent_results",
            "data_version": version,
            "season": games[0].season,
            "opponent_id": opponent,
            "team_ids": ["NYK", opponent],
            "game_ids": sorted(g.id for g in games),
            "dates": sorted({r["game_date"] for r in rows}),
            "season_types": sorted({g.season_type for g in games}),
            "canonical_sources": sorted(f"game:{g.nba_game_id}" for g in games),
            "canonical_rows": rows,
        },
        text,
    )


def identity_unit(player: Player, version: str) -> dict[str, Any]:
    row = {
        key: getattr(player, key)
        for key in ("nba_player_id", "full_name", "team_id", "position", "jersey_number")
    }
    aliases = sorted(_player_aliases(player))
    curated = {
        alias: name for alias, name in _CURATED_PLAYER_ALIASES.items() if name == player.full_name
    }
    display = [a.upper() if a in curated and len(a) <= 3 else a for a in aliases]
    text = (
        f"Canonical player identity: {player.full_name}; NBA player ID {player.nba_player_id}; "
        f"team {player.team_id}. Name-derived and project-curated aliases: {', '.join(display)}. "
        "Identity only; this does not identify a game or establish game performance."
    )
    return _record(
        {
            "unit_type": "player_identity",
            "data_version": version,
            "player_ids": [player.id],
            "player_names": [player.full_name],
            "team_ids": [player.team_id] if player.team_id else [],
            "canonical_player": row,
            "aliases": aliases,
            "alias_provenance": {"name_derived": True, "project_curated": curated},
            "canonical_sources": [f"player:{player.nba_player_id}"],
        },
        text,
    )


_MEASURE_FAMILIES = {
    "quarter": ("q3_fewest_points", "q3_worst_margin"),
    "deficit": (
        "largest_observed_deficit",
        "largest_deficit_later_tied",
        "largest_deficit_later_led",
        "largest_deficit_in_eventual_win",
    ),
    "runs": (
        "knicks_largest_unanswered_run",
        "opponent_largest_unanswered_run",
        "knicks_largest_unrestricted_net_gain",
        "largest_unrestricted_margin_decline",
    ),
    "collapse": (
        "largest_positive_lead_surrendered",
        "largest_positive_lead_surrendered_in_final_loss",
        "largest_unrestricted_margin_decline",
    ),
}
_FAMILY_TITLES = {
    "quarter": "Worst third quarter: fewest Knicks points versus worst scoring margin",
    "deficit": "Largest deficit: observed versus erased to a tie, lead or eventual win",
    "runs": (
        "Biggest Knicks scoring run and most damaging opponent run: unanswered points "
        "versus unrestricted net margins; a damage criterion still needs clarification"
    ),
    "collapse": "Worst collapse: positive lead surrendered versus unrestricted margin decline",
}


def unit_search_text(payload: dict[str, Any]) -> str:
    """Rank the supported subject; retain the complete proof as returned evidence."""
    if payload.get("unit_type") == "game_scoring_comparison" or payload.get("aggregate_kind") in {
        "measure_comparison",
        "selected_game_stories",
    }:
        return payload["text"].split("\n", 1)[0]
    return str(payload["semantic_summary"])


def _measure_sources(rows: list[dict]) -> list[str]:
    """Only metric witnesses earn refs; population labels are not generic game credit."""
    sources = set()
    for row in rows:
        for measure in row["measures"].values():
            for boundary in measure["boundaries"]:
                sources.update(boundary.get("period_sources", []))
                sources.update(boundary.get("scoring_sources", []))
                sources.update(
                    boundary[k] for k in ("source", "start_source", "end_source") if k in boundary
                )
    return sorted(sources)


def _witnesses(rows: list[dict], facts: dict) -> dict:
    result = {}
    for row in rows:
        supplied = facts[row["nba_game_id"]]["events"]
        result.update({key: supplied[key] for key in _measure_sources([row]) if key in supplied})
    return result


def _comparison_records(games: list[Game], version: str, proof: tuple) -> list[dict]:
    source, report, facts = proof
    game_map = {g.nba_game_id: g for g in games}
    compared = {g["nba_game_id"]: g for g in report["games"]}
    provenance = {
        "comparison_sha256": source.source_sha256,
        "source_review_sha256": source.source_review_sha256,
        "trajectories_sha256": source.trajectories_sha256,
        "bundle_sha256": source.bundle_sha256,
        "recipe": "nba-action-scoring-trajectory-v1",
    }
    records = []
    for scope, population in report["populations"].items():
        identities = [value.removeprefix("game:") for value in population["game_sources"]]
        if not identities or not set(identities) <= set(game_map):
            continue
        selected = [game_map[identity] for identity in identities]
        for family, keys in _MEASURE_FAMILIES.items():
            rows = [
                {
                    "nba_game_id": identity,
                    "game_id": game_map[identity].id,
                    "game_date": compared[identity]["game_date"],
                    "season_type": compared[identity]["season_type"],
                    "measures": {key: compared[identity]["measures"][key] for key in keys},
                }
                for identity in identities
            ]
            definitions = {key: report["definitions"][key] for key in keys}
            extrema = {key: population["extrema"][key] for key in keys}
            witnesses = _witnesses(rows, facts)
            body = {
                "definitions": definitions,
                "comparison_rows": rows,
                "extrema": extrema,
                "witness_events": witnesses,
            }
            text = (
                f"{_FAMILY_TITLES[family]}. NYK Knicks {report['games'][0]['season']}; "
                f"{scope}, complete population of {len(rows)} games. "
                "Quantitative alternatives only. No metric, window or season-scope default; "
                "no causal assertions.\n" + json.dumps(body, sort_keys=True, separators=(",", ":"))
            )
            records.append(
                _record(
                    {
                        "unit_type": "multigame_aggregate",
                        "aggregate_kind": "measure_comparison",
                        "measure_family": family,
                        "population_scope": scope,
                        "data_version": version,
                        "season": report["games"][0]["season"],
                        "team_ids": sorted(
                            {t for g in selected for t in (g.home_team_id, g.away_team_id)}
                        ),
                        "game_ids": sorted(g.id for g in selected),
                        "dates": sorted({g.game_date.isoformat() for g in selected}),
                        "season_types": sorted({g.season_type for g in selected}),
                        "canonical_sources": _measure_sources(rows),
                        **body,
                        "provenance": provenance,
                        "metric_defaults": None,
                        "gold_approved": False,
                        **({"start_period": 3, "end_period": 3} if family == "quarter" else {}),
                    },
                    text,
                )
            )
    for identity, game in game_map.items():
        row = compared[identity]
        detail = facts[identity]
        body = {
            "home_team_id": game.home_team_id,
            "away_team_id": game.away_team_id,
            "home_score": game.home_score,
            "away_score": game.away_score,
            "period_rows": detail["periods"],
            "measures": row["measures"],
            "definitions": report["definitions"],
            "witness_events": detail["events"],
        }
        text = (
            f"Knicks NYK game {identity}, {game.game_date.isoformat()}, {game.season_type}. "
            "Complete game scoring comparisons and descriptive story: final/period scores, "
            "all maximum unanswered scoring runs, deficits and explicitly unrestricted margins. "
            "No causal assertions or metric default.\n"
            + json.dumps(body, sort_keys=True, separators=(",", ":"))
        )
        records.append(
            _record(
                {
                    "unit_type": "game_scoring_comparison",
                    "data_version": version,
                    "game_id": game.id,
                    "game_ids": [game.id],
                    "nba_game_id": identity,
                    "date": game.game_date.isoformat(),
                    "season": game.season,
                    "season_type": game.season_type,
                    "team_ids": [game.home_team_id, game.away_team_id],
                    "canonical_sources": sorted(
                        {
                            f"game:{identity}",
                            *(p["canonical_id"] for p in detail["periods"]),
                            *_measure_sources([row]),
                        }
                    ),
                    **body,
                    "provenance": provenance,
                    "metric_defaults": None,
                    "gold_approved": False,
                },
                text,
            )
        )
    # Stable full-margin groups are indexed once; runtime never mints a subgroup.
    margin_groups: dict[int, list[str]] = defaultdict(list)
    for row in report["games"]:
        margin_groups[abs(row["final_nyk_margin"])].append(row["nba_game_id"])
    for identities in margin_groups.values():
        if len(identities) < 2 or not set(identities) <= set(game_map):
            continue
        story_games = [game_map[identity] for identity in identities]
        rows = [
            {
                "game_id": g.id,
                "nba_game_id": g.nba_game_id,
                "game_date": g.game_date.isoformat(),
                "season_type": g.season_type,
                "home_team_id": g.home_team_id,
                "away_team_id": g.away_team_id,
                "home_score": g.home_score,
                "away_score": g.away_score,
                "final_margin": abs(g.home_score - g.away_score),
                "period_rows": facts[g.nba_game_id]["periods"],
            }
            for g in sorted(story_games, key=lambda g: (g.game_date, g.nba_game_id))
        ]
        text = (
            "Closest Knicks NYK game descriptive story within this selected "
            "tied-final-margin population. "
            "Every selected game and period is represented; no causal assertion or "
            "comparison outside this supplied population.\n"
            + json.dumps(rows, sort_keys=True, separators=(",", ":"))
        )
        records.append(
            _record(
                {
                    "unit_type": "multigame_aggregate",
                    "aggregate_kind": "selected_game_stories",
                    "data_version": version,
                    "season": story_games[0].season,
                    "game_ids": sorted(g.id for g in story_games),
                    "team_ids": sorted(
                        {t for g in story_games for t in (g.home_team_id, g.away_team_id)}
                    ),
                    "dates": sorted({g.game_date.isoformat() for g in story_games}),
                    "season_types": sorted({g.season_type for g in story_games}),
                    "story_rows": rows,
                    "canonical_sources": sorted(
                        {f"game:{g.nba_game_id}" for g in story_games}
                        | {
                            p["canonical_id"]
                            for g in story_games
                            for p in facts[g.nba_game_id]["periods"]
                        }
                    ),
                    "provenance": provenance,
                    "gold_approved": False,
                },
                text,
            )
        )
    return records


def unit_is_in_scope(
    payload: dict[str, Any],
    selected_game_ids: set[int],
    player_ids: list[int],
    periods: list[int],
) -> bool:
    kind = payload["unit_type"]
    if kind == "player_identity":
        return set(payload["player_ids"]) <= set(player_ids)
    if kind not in {"multigame_aggregate", "game_scoring_comparison"}:
        return False
    if player_ids or not set(payload["game_ids"]) <= selected_game_ids:
        return False
    if kind == "multigame_aggregate" and "game_id" in payload:
        return False
    return not periods or (payload.get("measure_family") == "quarter" and set(periods) == {3})


def accepts_unit(
    metadata: dict[str, Any],
    *,
    unit_records: list[dict[str, Any]],
    selected_game_ids: set[int],
    player_ids: list[int],
    periods: list[int],
    version: str,
) -> bool:
    """Compare a receipt with the complete SQL/proof-bound corpus for this search."""
    if metadata.get("data_version") != version:
        return False
    expected = next(
        (r["payload"] for r in unit_records if r["id"] == metadata.get("source_document_id")), None
    )
    if expected is None:
        return False
    if not unit_is_in_scope(expected, selected_game_ids, player_ids, periods):
        return False
    return all(metadata.get(key) == value for key, value in expected.items())


async def build_archive_units(
    db: AsyncSession, games: list[Game], version: str
) -> list[dict[str, Any]]:
    release = (
        await db.execute(
            select(DatasetRelease).where(
                DatasetRelease.version == version, DatasetRelease.validation_passed.is_(True)
            )
        )
    ).scalar_one_or_none()
    if release is None or not games:
        return []
    population = list(
        (
            await db.execute(
                select(Game)
                .where(
                    Game.release_id == release.id,
                    Game.season == release.season,
                    Game.status == "final",
                    Game.home_score != Game.away_score,
                    (Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"),
                )
                .order_by(Game.game_date, Game.id)
            )
        ).scalars()
    )
    included = {g.id for g in games}
    groups: dict[str, list[Game]] = defaultdict(list)
    for game in population:
        opponent = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
        groups[opponent].append(game)
    records = [
        opponent_unit(group, opponent, version)
        for opponent, group in sorted(groups.items())
        if len(group) > 1 and {g.id for g in group} <= included
    ]
    players = list(
        (
            await db.execute(
                select(Player)
                .join(PlayerGameStat, PlayerGameStat.player_id == Player.id)
                .where(
                    PlayerGameStat.release_id == release.id,
                    PlayerGameStat.game_id.in_(included),
                    PlayerGameStat.team_id == "NYK",
                )
                .distinct()
                .order_by(Player.nba_player_id)
            )
        ).scalars()
    )
    records.extend(identity_unit(player, version) for player in players)
    selected = [g for g in population if g.id in included]
    proof = await verified_comparison_source(db, release, selected)
    if proof is not None:
        records.extend(_comparison_records(selected, version, proof))
    return sorted(records, key=lambda record: record["id"])
