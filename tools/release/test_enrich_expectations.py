"""Tamper and edge checks for independent expectation enrichment."""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


subject = load("expectation_subject")
enrich = load("enrich_expectations")


def game(game_id, day, own, allowed):
    return {
        "nba_game_id": game_id,
        "game_date": f"2026-01-{day:02d}",
        "home_team_id": "NYK",
        "away_team_id": "BOS",
        "home_score": own,
        "away_score": allowed,
        "season_type": "regular",
    }


def payload():
    body = {
        "data": {
            "games": [game("a", 1, 100, 90), game("b", 2, 95, 96), game("c", 3, 108, 99)],
            "players": [
                {"nba_player_id": 1, "full_name": "Test Player"},
                {"nba_player_id": 2, "full_name": "Other Player"},
            ],
            "player_game_stats": [
                {
                    "nba_game_id": "a",
                    "nba_player_id": 1,
                    "team_id": "NYK",
                    "minutes": 30,
                    "points": 16,
                    "rebounds": 4,
                    "assists": 3,
                    "starter": True,
                    "three_pointers_made": 1,
                    "three_pointers_attempted": 3,
                },
                {
                    "nba_game_id": "b",
                    "nba_player_id": 1,
                    "team_id": "NYK",
                    "minutes": 30,
                    "points": 14,
                    "rebounds": 6,
                    "assists": 2,
                    "starter": True,
                    "three_pointers_made": 2,
                    "three_pointers_attempted": 4,
                },
                {
                    "nba_game_id": "b",
                    "nba_player_id": 2,
                    "team_id": "NYK",
                    "minutes": 20,
                    "points": 9,
                    "rebounds": 1,
                    "assists": 1,
                    "starter": False,
                    "three_pointers_made": 0,
                    "three_pointers_attempted": 1,
                },
            ],
            "team_game_stats": [],
            "period_scores": [],
        },
    }
    body["manifest"] = {
        "version": "test.1",
        "content_sha256": subject.digest(body["data"]),
    }
    return body


def fact(metric, scope, value, evidence, **extra):
    return {
        "metric": metric,
        "scope": scope,
        "value": value,
        "canonical_evidence_ids": list(evidence),
        **extra,
    }


def review(facts, **extra):
    document = {
        "status": "review_preparation_not_final_approval_request",
        "case_count": 1,
        "semantic_case_count": 0,
        "proposed_dispositions": {"answer": 1},
        "cases": [
            {
                "id": "exact_statistics-001",
                "question": "How many games?",
                "category": "exact_statistics",
                "original_answerable": True,
                "original_route": "table_rag",
                "proposed_expectation": {
                    "answerable": True,
                    "canonical_evidence_ids": [],
                    "canonical_facts": facts,
                    "claims": [],
                    "disposition": "answer",
                    "expected_route": "table_rag",
                    "notes": [],
                    "required_facts": [],
                },
                "original_semantic_member": False,
                "semantic_targets": [],
                "semantic_status": "not_original_semantic_case",
                "provisional_canonical_support": [],
                "remaining_owner_decisions": [],
                "owner_approved": False,
            }
        ],
        "owner_approval": None,
        "frozen": False,
    }
    document.update(extra)
    return document


def archive():
    return subject.Archive(payload())


def test_team_subject_only_when_the_value_reproduces():
    facts = [fact("games", "archive", 3, ["game:a", "game:b", "game:c"])]
    proposal, changes, unresolved, _, families = enrich.enrich(review(facts), archive())
    stored = proposal["cases"][0]["proposed_expectation"]["canonical_facts"][0]
    assert stored["subject"] == "team:NYK"
    assert changes[0]["check"]["recomputed"] == 3
    assert not unresolved and families["team"]["changed"] == 1


def test_team_value_that_does_not_reproduce_stays_unresolved_with_the_reason():
    facts = [fact("games", "archive", 4, ["game:a", "game:b", "game:c"])]
    proposal, changes, unresolved, _, _ = enrich.enrich(review(facts), archive())
    stored = proposal["cases"][0]["proposed_expectation"]["canonical_facts"][0]
    assert "subject" not in stored and not changes
    assert "3" in unresolved[0]["reason"] and "4" in unresolved[0]["reason"]


def test_declared_player_name_is_confirmed_and_left_as_the_portable_identity():
    facts = [
        fact(
            "Test Player: total points",
            "archive",
            30,
            ["box:a:1", "box:b:1"],
            player_name="Test Player",
            appearances=2,
        )
    ]
    proposal, changes, unresolved, observations, families = enrich.enrich(review(facts), archive())
    stored = proposal["cases"][0]["proposed_expectation"]["canonical_facts"][0]
    assert stored["player_name"] == "Test Player" and "subject" not in stored
    assert not changes and not unresolved and not observations
    assert families["player"]["verified"] == 1


def test_player_name_outside_the_roster_stays_unresolved():
    facts = [
        fact(
            "Ghost Player: total points",
            "archive",
            30,
            ["box:a:1"],
            player_name="Ghost Player",
            appearances=1,
        )
    ]
    _, changes, unresolved, _, _ = enrich.enrich(review(facts), archive())
    assert not changes and "0 canonical players" in unresolved[0]["reason"]


def test_player_value_that_does_not_reproduce_is_reported_not_silently_kept():
    facts = [
        fact(
            "Test Player: total points",
            "archive",
            31,
            ["box:a:1", "box:b:1"],
            player_name="Test Player",
            appearances=2,
        )
    ]
    _, changes, unresolved, observations, _ = enrich.enrich(review(facts), archive())
    assert not changes and not unresolved
    assert observations[0]["value_check"] == "mismatch:30"


def tied_archive():
    document = payload()
    document["data"]["player_game_stats"].append(
        {
            "nba_game_id": "a",
            "nba_player_id": 2,
            "team_id": "NYK",
            "minutes": 25,
            "points": 21,
            "rebounds": 3,
            "assists": 2,
            "starter": True,
            "three_pointers_made": 1,
            "three_pointers_attempted": 2,
        }
    )
    document["manifest"]["content_sha256"] = subject.digest(document["data"])
    return subject.Archive(document)


def test_tied_leader_stays_unresolved():
    facts = [
        fact(
            "points leader",
            "archive",
            {"name": "Test Player", "total": 30},
            ["box:a:1", "box:a:2", "box:b:1", "box:b:2"],
        )
    ]
    _, changes, unresolved, _, _ = enrich.enrich(review(facts), tied_archive())
    assert not changes and "leader is [1, 2]" in unresolved[0]["reason"]


def test_scoreline_takes_the_runtime_team_subject_only_on_an_exact_row():
    row = payload()["data"]["games"][0]
    scoreline = {
        key: row[key]
        for key in (
            "nba_game_id",
            "game_date",
            "home_team_id",
            "away_team_id",
            "home_score",
            "away_score",
        )
    }
    facts = [fact("game_score", "archive", scoreline, ["game:a"])]
    proposal, changes, unresolved, _, _ = enrich.enrich(review(facts), archive())
    stored = proposal["cases"][0]["proposed_expectation"]["canonical_facts"][0]
    assert stored["subject"] == "team:NYK"
    assert changes[0]["check"]["kind"] == "game_row" and not unresolved
    broken = [fact("game_score", "archive", {"nba_game_id": "a"}, ["game:a"])]
    _, changes, unresolved, _, _ = enrich.enrich(review(broken), archive())
    assert not changes and "differs from bundle row" in unresolved[0]["reason"]


def test_only_identity_fields_change_and_stripping_restores_the_input():
    facts = [
        fact("games", "archive", 3, ["game:a", "game:b", "game:c"]),
        fact(
            "points leader",
            "archive",
            {"name": "Test Player", "total": 30},
            ["box:a:1", "box:b:1"],
        ),
    ]
    document = review(facts)
    raw = enrich.rendered(document).encode()
    proposal, changes, _, _, _ = enrich.enrich(document, archive())
    assert enrich.preservation(raw, document, proposal, changes)["stripped_proposal_equals_input"]
    stored = proposal["cases"][0]["proposed_expectation"]["canonical_facts"]
    assert stored[0]["value"] == 3 and stored[1]["value"]["total"] == 30
    assert subject.digest(enrich.stripped(proposal, changes)) == subject.digest(document)


def test_any_change_other_than_an_identity_field_is_refused():
    facts = [fact("games", "archive", 3, ["game:a", "game:b", "game:c"])]
    document = review(facts)
    raw = enrich.rendered(document).encode()
    proposal, changes, _, _, _ = enrich.enrich(document, archive())
    proposal["cases"][0]["proposed_expectation"]["canonical_facts"][0]["value"] = 4
    with pytest.raises(enrich.EnrichmentError):
        enrich.preservation(raw, document, proposal, changes)


def test_an_approved_or_frozen_review_is_not_enriched():
    facts = [fact("games", "archive", 3, ["game:a", "game:b", "game:c"])]
    for override in ({"owner_approval": "owner"}, {"frozen": True}):
        document = review(facts, **override)
        raw = enrich.rendered(document).encode()
        proposal, changes, _, _, _ = enrich.enrich(document, archive())
        with pytest.raises(enrich.EnrichmentError):
            enrich.preservation(raw, document, proposal, changes)


def write_inputs(tmp_path, document, payload_bytes):
    bundle = tmp_path / "bundle.json.gz"
    bundle.write_bytes(payload_bytes)
    labels = tmp_path / "labels.jsonl"
    labels.write_text("{}\n")
    document["labels_sha256"] = hashlib.sha256(labels.read_bytes()).hexdigest()
    review_path = tmp_path / "review.json"
    review_path.write_text(enrich.rendered(document))
    return bundle, labels, review_path


def test_cli_refuses_a_bundle_whose_sha_is_not_the_pinned_one(tmp_path):
    document = review([fact("games", "archive", 3, ["game:a", "game:b", "game:c"])])
    raw = gzip.compress(json.dumps(payload()).encode())
    bundle, labels, review_path = write_inputs(tmp_path, document, raw)
    out = tmp_path / "out"
    with pytest.raises(SystemExit):
        enrich.main(
            [
                "--review",
                str(review_path),
                "--bundle",
                str(bundle),
                "--bundle-sha256",
                "0" * 64,
                "--labels",
                str(labels),
                "--output-dir",
                str(out),
            ]
        )
    assert not out.exists()


def test_cli_refuses_labels_that_do_not_match_the_review(tmp_path):
    document = review([fact("games", "archive", 3, ["game:a", "game:b", "game:c"])])
    raw = gzip.compress(json.dumps(payload()).encode())
    bundle, labels, review_path = write_inputs(tmp_path, document, raw)
    document["labels_sha256"] = "0" * 64
    review_path.write_text(enrich.rendered(document))
    with pytest.raises(SystemExit):
        enrich.main(
            [
                "--review",
                str(review_path),
                "--bundle",
                str(bundle),
                "--bundle-sha256",
                hashlib.sha256(raw).hexdigest(),
                "--labels",
                str(labels),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )


def test_cli_writes_a_bound_proposal_and_report(tmp_path):
    document = review([fact("games", "archive", 3, ["game:a", "game:b", "game:c"])])
    raw = gzip.compress(json.dumps(payload()).encode())
    bundle, labels, review_path = write_inputs(tmp_path, document, raw)
    out = tmp_path / "out"
    assert (
        enrich.main(
            [
                "--review",
                str(review_path),
                "--bundle",
                str(bundle),
                "--bundle-sha256",
                hashlib.sha256(raw).hexdigest(),
                "--labels",
                str(labels),
                "--output-dir",
                str(out),
            ]
        )
        == 0
    )
    report = json.loads((out / enrich.REPORT_NAME).read_text())
    proposed = out / enrich.PROPOSED_NAME
    assert report["binding"]["proposed_sha256"] == hashlib.sha256(proposed.read_bytes()).hexdigest()
    assert report["preserved"]["stripped_proposal_equals_input"]
    assert report["proposal"]["eligible_for_gold_labels"] is False
    assert report["proposal"]["owner_approval"] is None
    assert report["changes"][0]["added"] == {"subject": "team:NYK"}
