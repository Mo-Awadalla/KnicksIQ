"""Complete opponent source units through indexing, HTTP ranking and mappings."""

import gzip
import hashlib
import json
import os
from pathlib import Path

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.runtime_mapping import resolve_runtime_mapping
from app.evaluation.trace_capture import capture_turn
from app.services import analyst_loop
from app.services.rag_index import build_rag_artifacts
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, SHA
from httpx import ASGITransport, AsyncClient


async def test_complete_atl_unit_is_actually_ranked_and_independently_mapped(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,  # noqa: F811
):
    settings = get_settings()
    for name, value in {
        "analyst_evidence_loop_enabled": True,
        "analysis_answer_mode": "disabled",
        "rag_qdrant_enabled": False,
    }.items():
        monkeypatch.setattr(settings, name, value)
    attempts = 0

    def denied():
        nonlocal attempts
        attempts += 1
        raise AssertionError("Archive unit proof cannot construct a provider")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", denied)
    source = json.loads(gzip.decompress(BUNDLE.read_bytes()))
    expected = {
        g["nba_game_id"]: g
        for g in source["data"]["games"]
        if "ATL" in {g["home_team_id"], g["away_team_id"]}
    }
    directory = Path(os.environ.get("KNICKSIQ_UNITS_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        index = await build_rag_artifacts(
            db,
            season="2025-26",
            out_dir=directory / "index",
            data_version=source["manifest"]["version"],
        )
    payload = {"question": "How did they do v ATL?", "turn_id": "archive-units-atl-proof"}
    async with AsyncClient(
        transport=ASGITransport(client._transport.app, client=("192.0.2.231", 12345)),
        base_url="http://test",
    ) as http:
        with capture_turn() as capture:
            response = await http.post("/analysis/query", json=payload)
        replay = await http.post("/analysis/query", json=payload)
    receipt = {
        "request": payload,
        "http_status": response.status_code,
        "response": response.json(),
        "replay": replay.json(),
        "capture": capture,
        "index": index,
        "expected_atl_games_from_raw_bundle": sorted(expected),
        "provider_attempts": attempts,
    }
    with (directory / "atl-http.json").open("x") as artifact:
        json.dump(receipt, artifact, indent=2)
    assert response.status_code == 200 and attempts == 0
    assert replay.json() == response.json()
    search = capture["searches"][0]
    ranked = search["returned_evidence_ids"][:5]
    observed = [e for e in search["evidence"] if e["evidence_id"] in ranked]
    aggregate = next(
        (e for e in observed if e["metadata"].get("unit_type") == "multigame_aggregate"), None
    )
    assert aggregate is not None, ranked
    assert aggregate["game_id"] is None and "game_id" not in aggregate["metadata"]
    rows = aggregate["metadata"]["canonical_rows"]
    assert len(rows) == len(expected) == 9
    assert {r["nba_game_id"] for r in rows} == set(expected)
    for row in rows:
        raw = expected[row["nba_game_id"]]
        for field in (
            "game_date",
            "season_type",
            "home_team_id",
            "away_team_id",
            "home_score",
            "away_score",
        ):
            assert row[field] == raw[field]
        assert row["nba_game_id"] in aggregate["text"]
        assert row["game_date"] in aggregate["text"]
        assert str(row["home_score"]) in aggregate["text"]
        assert str(row["away_score"]) in aggregate["text"]
    targets = sorted(f"game:{identity}" for identity in expected)
    assert aggregate["metadata"]["canonical_sources"] == targets
    indexed = [
        json.loads(line)
        for line in (directory / "index" / "archive_units.jsonl").read_text().splitlines()
    ]
    indexed_atl = next(r for r in indexed if r["payload"].get("opponent_id") == "ATL")
    assert (
        indexed_atl["payload"]["source_document_id"] == aggregate["metadata"]["source_document_id"]
    )
    manifest = {
        "release_id": aggregate["release_id"],
        "bundle_sha256": SHA,
        "documents": {
            aggregate["evidence_id"]: {
                "evidence_sha256": hashlib.sha256(
                    json.dumps(aggregate, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "canonical_sources": targets,
            }
        },
    }
    manifest_path = directory / "independently-checked-atl-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    mapping = resolve_runtime_mapping(
        manifest_path,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        aggregate["release_id"],
        SHA,
        [aggregate],
    )
    with (directory / "atl-mapping.json").open("x") as artifact:
        json.dump(mapping, artifact, indent=2)
    assert set(mapping["mapping"][aggregate["evidence_id"]]) == set(targets)
    assert mapping["quality_approved"] is False

    followups = [
        {
            "question": "How did the Knicks do against ATL in the regular season?",
            "turn_id": "archive-units-narrow-proof",
        },
        {"question": "How did JB play in that game?", "turn_id": "archive-units-identity-proof"},
    ]
    for index, request in enumerate(followups):
        async with AsyncClient(
            transport=ASGITransport(
                client._transport.app, client=(f"192.0.2.{232 + index}", 12345)
            ),
            base_url="http://test",
        ) as http:
            with capture_turn() as scope_capture:
                result = await http.post("/analysis/query", json=request)
        with (directory / f"scope-{index}.json").open("x") as artifact:
            json.dump(
                {"request": request, "response": result.json(), "capture": scope_capture},
                artifact,
                indent=2,
            )
        assert result.status_code == 200
        docs = scope_capture["searches"][0]["evidence"]
        if index == 0:
            assert not any(d["metadata"].get("unit_type") == "multigame_aggregate" for d in docs)
        else:
            assert result.json()["route"] == "clarification"
            assert not result.json()["citations"]
            identity = next(d for d in docs if d["metadata"].get("unit_type") == "player_identity")
            assert identity["evidence_id"] in scope_capture["searches"][0]["returned_evidence_ids"]
            canonical = next(p for p in source["data"]["players"] if p["nba_player_id"] == 1628973)
            assert identity["metadata"]["canonical_player"]["full_name"] == canonical["full_name"]
            assert identity["metadata"]["canonical_sources"] == ["player:1628973"]
            assert "JB" in identity["text"]
    assert attempts == 0
    async with AsyncSessionLocal() as db:
        await build_rag_artifacts(
            db,
            season="2025-26",
            out_dir=directory / "repeat-index",
            data_version=source["manifest"]["version"],
        )
    assert (directory / "repeat-index/archive_units.jsonl").read_bytes() == (
        directory / "index/archive_units.jsonl"
    ).read_bytes()
