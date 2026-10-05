"""Verified comparison import/index/ranking through real SQL, HTTP and Redis.

Specified before source-store and runtime integration code. Portable fixtures
are independent NBA-action examples, never release gold or hosted evidence.
"""

import copy
import hashlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.comparison_source import ComparisonSource
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.comparison_sources import import_comparison_source
from app.services.rag_index import build_rag_artifacts
from app.services.release_bundle import build_bundle, canonical_json, load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_discovery_http import configure, exchange
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[4]


def independent_inputs(directory):
    prototype, capture = runpy.run_path(
        str(ROOT / "tools/release/check_derived_scoring.py"), run_name="fixture"
    )["fixture"]()
    data = prototype["data"]
    data["teams"] = [
        {"id": team, "nba_team_id": number, "name": name, "city": city, "abbreviation": team}
        for team, number, name, city in (
            ("NYK", 1610612752, "Knicks", "New York"),
            ("BOS", 1610612738, "Celtics", "Boston"),
        )
    ]
    data["players"] = [
        {
            "nba_player_id": player,
            "team_id": team,
            "full_name": name,
            "position": "G",
            "jersey_number": "1",
        }
        for player, team, name in ((11, "NYK", "Fixture Alpha"), (22, "BOS", "Fixture Beta"))
    ]
    original = copy.deepcopy(data)
    for collection in ("games", "events", "period_scores", "player_game_stats"):
        for row in original[collection]:
            second = copy.deepcopy(row)
            second["nba_game_id"] = "fixture-postseason"
            if collection == "games":
                second["season_type"] = "playoffs"
                second["game_date"] = "2026-02-01"
            data[collection].append(second)
    data["team_game_stats"], data["reports"] = [], []
    approvals = {}
    for game in data["games"]:
        identity = game["nba_game_id"]
        game.update(
            source_name="Independent fixture",
            source_game_id=identity,
            source_url=f"https://www.nba.com/game/{identity}",
            source_fetched_at="2026-10-03T00:00:00+00:00",
            source_payload_hash=hashlib.sha256(identity.encode()).hexdigest(),
            data_status="analysis_ready",
        )
        report = {
            "nba_game_id": identity,
            "report_type": "postgame",
            "title": "Independent fixture report",
            "summary": "Fixture summary",
            "reviewed": True,
        }
        data["reports"].append(report)
        approvals[identity] = hashlib.sha256(
            canonical_json({k: v for k, v in report.items() if k != "reviewed"})
        ).hexdigest()
        for row in data["player_game_stats"]:
            if row["nba_game_id"] != identity:
                continue
            row["minutes"] = 24.0
            data["team_game_stats"].append(
                {k: v for k, v in row.items() if k not in {"nba_player_id", "minutes"}}
            )
    prototype["manifest"].update(
        version="comparison-fixture.1",
        source="Independent fixture",
        expected_games=2,
        expected_game_ids=[g["nba_game_id"] for g in data["games"]],
    )
    prototype["review_manifest"] = {"approvals": approvals}
    bundle = directory / "bundle.json.gz"
    bundle_sha = build_bundle(prototype, bundle)
    official = directory / "official"
    official.mkdir()
    for game in data["games"]:
        value = copy.deepcopy(capture)
        value["play_by_play"]["gameId"] = game["nba_game_id"]
        value["source_url"] = f"https://www.nba.com/game/{game['nba_game_id']}/play-by-play"
        (official / f"{game['nba_game_id']}.json").write_text(json.dumps(value, indent=2))
    commands = [
        [
            sys.executable,
            str(ROOT / "tools/release/verify_derived_scoring.py"),
            "--bundle",
            str(bundle),
            "--expected-bundle-sha256",
            bundle_sha,
            "--official-dir",
            str(official),
            "--output",
            str(directory / "derived"),
        ],
    ]
    result = subprocess.run(commands[0], capture_output=True, text=True, timeout=30)
    (directory / "source-cli.json").write_text(
        json.dumps(
            {
                "argv": commands[0],
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            indent=2,
        )
    )
    assert result.returncode == 0, result.stderr
    paths = {
        "bundle": bundle,
        "trajectories": directory / "derived/derived-scoring-events.jsonl",
        "source_review": directory / "derived/derived-source-review.json",
    }
    hashes = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()}
    command = [
        sys.executable,
        str(ROOT / "tools/release/build_measure_comparisons.py"),
        "--trajectories",
        str(paths["trajectories"]),
        "--expected-trajectories-sha256",
        hashes["trajectories"],
        "--source-review",
        str(paths["source_review"]),
        "--expected-source-review-sha256",
        hashes["source_review"],
        "--output",
        str(directory / "comparisons"),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    (directory / "comparison-cli.json").write_text(
        json.dumps(
            {
                "argv": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            indent=2,
        )
    )
    assert result.returncode == 0, result.stderr
    paths["comparisons"] = directory / "comparisons/measure-comparisons.json"
    hashes["comparisons"] = hashlib.sha256(paths["comparisons"].read_bytes()).hexdigest()
    return paths, hashes


async def test_snapshot_fast_path_preserves_noncanonical_proof_and_mutation_rejection(
    db_session, tmp_path
):
    from app.models.dataset_release import DatasetRelease
    from app.services.comparison_sources import verified_comparison_source

    paths, hashes = independent_inputs(tmp_path)
    loaded = await load_release_bundle(
        db_session, paths["bundle"], expected_sha256=hashes["bundle"], activate=True
    )
    source = await import_comparison_source(db_session, **paths, expected_hashes=hashes)
    release = (
        await db_session.execute(
            select(DatasetRelease).where(DatasetRelease.version == loaded.version)
        )
    ).scalar_one()
    games = list(
        (await db_session.execute(select(Game).where(Game.release_id == release.id))).scalars()
    )
    original = await verified_comparison_source(db_session, release, games)
    assert original is not None
    # Whitespace changes remain semantically equivalent, as the original verifier
    # allows; the canonical-byte fast path must retain that compatibility.
    source.facts_json = json.dumps(json.loads(source.facts_json), indent=2)
    source.bindings_json = json.dumps(json.loads(source.bindings_json), indent=2)
    await db_session.flush()
    equivalent = await verified_comparison_source(db_session, release, games)
    assert equivalent is not None and equivalent[1:] == original[1:]
    changed = json.loads(source.facts_json)
    changed["foreign-proof-fact"] = {"points": 999}
    source.facts_json = json.dumps(changed)
    await db_session.flush()
    with pytest.raises(ValueError, match="Stored comparison facts or bindings changed"):
        await verified_comparison_source(db_session, release, games)


async def test_import_index_and_actual_clarification_source_transitions(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
):
    directory = Path(os.environ.get("KNICKSIQ_MEASURE_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    proof_path = os.environ.get("KNICKSIQ_DISCOVERY_COMPARISON_INPUTS")
    if proof_path:
        proof = json.loads(Path(proof_path).read_text())
        paths = {name: Path(path) for name, path in proof["paths"].items()}
        hashes = proof["expected_hashes"]
    else:
        paths, hashes = independent_inputs(directory)
    expected_games = {
        row["nba_game_id"]: row for row in json.loads(paths["comparisons"].read_text())["games"]
    }
    attempts = configure(monkeypatch, "disabled")
    original_bytes = paths["bundle"].read_bytes()
    monkeypatch.setattr(get_settings(), "rag_qdrant_enabled", False)
    await local_redis.set("measure-source-accounting-control", "0.125")
    async with AsyncSessionLocal() as db:
        loaded = await load_release_bundle(
            db, paths["bundle"], expected_sha256=hashes["bundle"], activate=True
        )
        for name in paths:
            changed = {**hashes, name: "0" * 64}
            with pytest.raises(ValueError):
                await import_comparison_source(db, **paths, expected_hashes=changed)
            assert (await db.scalar(select(func.count()).select_from(ComparisonSource))) == 0
        await import_comparison_source(db, **paths, expected_hashes=hashes)
        await import_comparison_source(db, **paths, expected_hashes=hashes)
        assert (await db.scalar(select(func.count()).select_from(ComparisonSource))) == 1
        await build_rag_artifacts(
            db, season="2025-26", data_version=loaded.version, out_dir=directory / "index"
        )
    cases = [
        ("Describe the Knicks' worst third quarter.", "quarter"),
        ("How did the Knicks erase their largest deficit?", "deficit"),
        ("What was the most damaging opponent run this season?", "runs"),
        ("What was the Knics biggest run?", "runs"),
        ("What was NY's worst collpase?", "collapse"),
    ]
    receipts = []
    for index, (question, family) in enumerate(cases):
        async with AsyncClient(
            transport=ASGITransport(
                client._transport.app, client=(f"192.0.2.{210 + index}", 12345)
            ),
            base_url="http://test",
        ) as http:
            receipt = await exchange(
                http,
                {
                    "question": question,
                    "season": "2025-26",
                    "context": [],
                    "turn_id": f"measure-source-{index}",
                    "expected_revision": 0,
                },
            )
        receipts.append(receipt)
        (directory / f"http-{index}.json").write_text(json.dumps(receipt, indent=2))
        assert receipt["http_status"] == receipt["replay_status"] == 200
        assert receipt["replay"] == receipt["response"] and receipt["conflict_status"] == 409
        assert receipt["response"]["route"] == "clarification"
        search = receipt["capture"]["searches"][0]
        observed = [
            r for r in search["evidence"] if r["evidence_id"] in search["returned_evidence_ids"]
        ]
        matches = [r for r in observed if r["metadata"].get("measure_family") == family]
        assert matches, search["returned_evidence_ids"]
        for item in matches:
            assert item["game_id"] is None and "game_id" not in item["metadata"]
            assert set(item["metadata"]["game_ids"]) <= set(search["filters"]["game_ids"])
            assert item["metadata"]["gold_approved"] is False
        if family == "quarter":
            rows = matches[0]["metadata"]["comparison_rows"]
            assert {r["nba_game_id"] for r in rows} == set(expected_games)
            assert all(
                r["measures"]["q3_fewest_points"]
                == expected_games[r["nba_game_id"]]["measures"]["q3_fewest_points"]
                for r in rows
            )
        assert receipt["replay_capture"]["searches"] == []
    indexed_before = (directory / "index/archive_units.jsonl").read_bytes()
    async with AsyncSessionLocal() as db:
        event = (
            (
                await db.execute(
                    select(GameEvent)
                    .join(Game)
                    .where(
                        GameEvent.sequence == 1,
                        Game.release_id == select(ComparisonSource.release_id).scalar_subquery(),
                    )
                    .order_by(GameEvent.id)
                )
            )
            .scalars()
            .first()
        )
        assert event is not None
        old_clock = event.clock
        event.clock = "10:59"
        await db.commit()
        with pytest.raises(ValueError):
            await build_rag_artifacts(
                db,
                season="2025-26",
                data_version=loaded.version,
                out_dir=directory / "corrupt-index",
            )
        event.clock = old_clock
        await db.commit()
        await build_rag_artifacts(
            db, season="2025-26", data_version=loaded.version, out_dir=directory / "repeat-index"
        )
    assert (directory / "repeat-index/archive_units.jsonl").read_bytes() == indexed_before
    assert paths["bundle"].read_bytes() == original_bytes
    assert await local_redis.get("measure-source-accounting-control") == b"0.125"
    assert attempts == {"provider": 0, "dense": 0, "reservations": 0}
    (directory / "e2e-result.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "scope": "Portable SQL/HTTP source integrity, not approved gold",
                "attempts": attempts,
                "fixture_hashes": hashes,
                "artifacts": {
                    str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(directory.rglob("*"))
                    if p.is_file()
                },
            },
            indent=2,
        )
        + "\n"
    )
