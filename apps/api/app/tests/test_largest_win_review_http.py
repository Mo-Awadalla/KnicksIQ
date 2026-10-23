"""Largest-win packing through TCP HTTP, approved SQL archive and Redis replay."""

import gzip
import json
import os
import traceback
from copy import deepcopy
from pathlib import Path

import pytest
from app.core.db import AsyncSessionLocal
from app.models.game import Game
from app.services import analyst_loop
from app.services.release_bundle import build_bundle, load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import (
    SyntheticAdapter,
    assert_committed_replay,
    configure,
    save_receipt,
)
from app.tests.test_canonical_narrative_http import BUNDLE, SHA
from app.tests.test_record_availability_http import record_exchange
from jsonschema import Draft202012Validator
from sqlalchemy import select

QUESTION = "What was the Knicks biggest win by margin?"
FOLLOW_UPS = [
    "What was the Knicks' largest loss by margin?",
    "How many Knicks wins and losses are in the available archive?",
]
LONG_FOLLOW_UPS = [
    "Within the same available archive, what was the Knicks' largest loss by final scoring "
    "margin, including its date, final score and any games tied for that result?",
    "Across the archived regular-season and playoff games, how many games did the Knicks "
    "win and lose, and how many archived games does that record cover?",
]
STOPPED_TEXT = (
    "The Knicks' largest win by margin in the available archive was a 54-point win "
    "over Brooklyn on 2026-01-21, final score NYK 120, BKN 66. This is based on "
    "the available release archive (69 games compared across regular season and "
    "playoffs) and does not establish causation or overall playing quality."
)


def margin(game):
    return (game["home_score"] - game["away_score"]) * (1 if game["home_team_id"] == "NYK" else -1)


async def source_archive(tmp_path, behavior):
    scoring = behavior in {"highest", "lowest"}
    bundle, digest = BUNDLE, SHA
    if behavior == "tied":
        bundle = Path(__file__).with_name("fixtures") / "synthetic-archive.json.gz"
    archive = json.loads(gzip.decompress(bundle.read_bytes()))
    source = archive["data"]
    adjustments = []
    if behavior == "tied" or (not scoring and not os.environ.get("KNICKSIQ_APPROVED_BUNDLE")):
        games = source["games"]
        maximum = max(margin(g) for g in games)
        selected = [g for g in games if margin(g) == maximum][: 2 if behavior == "tied" else 1]
        for game in selected:
            assert game["home_team_id"] == "NYK"
            game["home_score"] += 1
            events = [e for e in source["events"] if e["nba_game_id"] == game["nba_game_id"]]
            for event in events:
                if event["home_score"] > 0:
                    event["home_score"] += 1
                    if event.get("score_margin") is not None:
                        event["score_margin"] += 1
            scorer = next(
                row
                for row in source["player_game_stats"]
                if row["nba_game_id"] == game["nba_game_id"] and row["team_id"] == "NYK"
            )
            scorer["points"] += 1
            scorer["free_throws_made"] += 1
            scorer["free_throws_attempted"] += 1
            team = next(
                row
                for row in source["team_game_stats"]
                if row["nba_game_id"] == game["nba_game_id"] and row["team_id"] == "NYK"
            )
            for field in ("points", "free_throws_made", "free_throws_attempted"):
                team[field] += 1
            period = next(
                row
                for row in source["period_scores"]
                if row["nba_game_id"] == game["nba_game_id"] and row["team_id"] == "NYK"
            )
            period["points"] += 1
            adjustments.append(game["nba_game_id"])
        bundle = tmp_path / "largest-win-derived.json.gz"
        digest = build_bundle(archive, bundle)
    games = [
        g
        for g in source["games"]
        if g["status"] == "final"
        and "NYK" in {g["home_team_id"], g["away_team_id"]}
        and (scoring or margin(g) > 0)
    ]

    def measure(game):
        return (
            (game["home_score"] if game["home_team_id"] == "NYK" else game["away_score"])
            if scoring
            else margin(game)
        )

    maximum = (min if behavior == "lowest" else max)(map(measure, games))
    selected = [g for g in games if measure(g) == maximum]
    async with AsyncSessionLocal() as db:
        release = await load_release_bundle(db, bundle, expected_sha256=digest, activate=True)
        ids = {
            g.nba_game_id: g.id
            for g in (
                await db.execute(select(Game).where(Game.release_id == release.release_id))
            ).scalars()
        }
    expected = {
        "margin": maximum,
        "metrics": ["game_score"] if scoring else ["game_score", "margin"],
        "comparison_game_ids": sorted(ids[g["nba_game_id"]] for g in games),
        "selected_game_ids": sorted(ids[g["nba_game_id"]] for g in selected),
        "scores": {
            str(ids[g["nba_game_id"]]): {
                g["home_team_id"]: g["home_score"],
                g["away_team_id"]: g["away_score"],
            }
            for g in selected
        },
        "archive_sha256": digest,
        "fixture_adjustments": adjustments,
    }
    if scoring:
        text = " ".join(
            f"The Knicks' {behavior}-scoring game in the available archive was on "
            f"{g['game_date']}, final score {g['home_team_id']} {g['home_score']}, "
            f"{g['away_team_id']} {g['away_score']}."
            for g in selected
        ) + (
            f" This compares the Knicks' final point totals across all {len(games)} "
            "final archived games, including regular season and playoffs and every tied result. "
            "The result describes the available release archive; it does not establish "
            "causation, overall team quality, or the result of games outside that archive."
        )
        if os.environ.get("KNICKSIQ_APPROVED_BUNDLE"):
            assert len(games) == 101 and len(selected) == 1
            assert maximum == (146 if behavior == "highest" else 80)
    elif os.environ.get("KNICKSIQ_APPROVED_BUNDLE") and behavior != "tied":
        assert maximum == 54 and len(games) == 69 and len(selected) == 1
        assert selected[0]["nba_game_id"] == "0022500622"
        text = STOPPED_TEXT
    else:
        text = " ".join(
            f"The Knicks' largest win by margin was a {maximum}-point win on {g['game_date']}, "
            f"final score {g['home_team_id']} {g['home_score']}, "
            f"{g['away_team_id']} {g['away_score']}."
            for g in selected
        ) + (
            f" This is based on the available release archive ({len(games)} games compared "
            "across regular season and playoffs) and does not establish causation "
            "or overall playing quality."
        )
    if behavior == "false-margin":
        text = text.replace(f"{maximum}-point", f"{maximum + 1}-point")
    if behavior == "long-supported":
        text += (
            " The comparison includes every archived Knicks win in those two phases. "
            f"The selected game itself is a {selected[0]['season_type']}-season game. "
            "The displayed margin is the difference between the two final team scores. "
            "The ranking applies to final scoring margin within this archive. "
            "Exactly one archived game attained this winning margin."
        )
        assert 550 <= len(text.encode()) <= 700
    return expected, text


class LargestWinAdapter(SyntheticAdapter):
    response_schema: dict | None = None

    def __init__(self, text, behavior):
        super().__init__({})
        self.text, self.behavior = text, behavior
        self.follow_ups = (
            LONG_FOLLOW_UPS if behavior in {"long-supported", "highest", "lowest"} else FOLLOW_UPS
        )

    async def generate(self, *, system, user):
        payload = json.loads(user)
        claims = analyst_loop.payload_claims(payload)
        evidence = analyst_loop.payload_evidence(payload)
        cited = sorted(
            {ref for c in claims for ref in c["supporting_evidence_ids"]}
            & {e["evidence_id"] for e in evidence}
        )
        if payload["schema"]["title"] == "AnswerReview":
            value = {
                "assertions": [
                    {
                        "text": span,
                        "assertion_type": "factual",
                        "verdict": "unsupported"
                        if self.behavior == "false-margin" and index == 0
                        else "supported",
                        "offending_text": span.strip()
                        if self.behavior == "false-margin" and index == 0
                        else None,
                        "supporting_claim_ids": [c["claim_id"] for c in claims],
                        "supporting_evidence_ids": cited,
                        "reason": "Margin wording conflicts with the native score."
                        if self.behavior == "false-margin" and index == 0
                        else "Native score, population and limitations support this statement.",
                    }
                    for index, span in enumerate(payload["review_spans"])
                ],
                "follow_up_reviews": [
                    {
                        "text": question,
                        "verdict": "supported",
                        "supporting_claim_ids": [c["claim_id"] for c in claims],
                        "supporting_evidence_ids": [],
                        "reason": "The archive supports final margins and complete game results.",
                    }
                    for question in payload["follow_up_questions"]
                ],
            }
        else:
            assert claims and cited
            answer = {
                "text": self.text,
                "claims": [
                    {"claim_id": c["claim_id"], "displayed_value": c["value"]} for c in claims
                ],
                "evidence_ids": cited,
                "fact_ids": [],
                "follow_up_questions": self.follow_ups,
            }
            value = (
                answer
                if payload["schema"]["title"] == "ProposedAnswer"
                else {"action": "answer_from_available_evidence", "tools": [], "answer": answer}
            )
        raw = json.dumps(analyst_loop.encode_model_response(payload, value))
        assert self.response_schema is not None
        Draft202012Validator.check_schema(self.response_schema)
        validator = Draft202012Validator(self.response_schema)
        wire = json.loads(raw)
        validator.validate(wire)
        adversarial = []
        if payload["schema"]["title"] == "AnswerReview":
            for collection, index_key in (
                ("assertions", "span_index"),
                ("follow_up_reviews", "follow_up_index"),
            ):
                for key, bad in (
                    ("supporting_claim_ids", ["claim:unknown"]),
                    ("supporting_evidence_ids", ["calculation:unknown"]),
                    *(
                        (support_key, bad_values)
                        for support_key in ("supporting_claim_ids", "supporting_evidence_ids")
                        for bad_values in ([-1], [9999], [True], [0.5], [None])
                    ),
                    (index_key, 9999),
                    (index_key, "0"),
                    (index_key, None),
                    ("reason", None),
                    ("verdict", None),
                    ("text", "An unsealed replacement span."),
                    ("extra", True),
                ):
                    changed = deepcopy(wire)
                    changed[collection][0][key] = bad
                    rejected = not validator.is_valid(changed)
                    adversarial.append(
                        {
                            "collection": collection,
                            "field": key,
                            "bad_value": bad,
                            "rejected": rejected,
                        }
                    )
                    assert rejected, adversarial[-1]
        self.inputs.append(
            {
                "system": system,
                "user": payload,
                "schema": self.response_schema,
                "raw_response": raw,
                "schema_valid": True,
                "schema_adversarial": adversarial,
                "input_bytes": len((system + user).encode())
                + len(analyst_loop.encoded(self.response_schema).encode()),
            }
        )
        return raw


def verify_native(receipt, expected):
    state = receipt["capture"]["turn"]["delivered_state"]
    assert state == receipt["capture"]["turn"]["committed_evidence_proposal"]
    native = {c["claim_id"]: c for c in state["claims"]}
    evidence = {e["evidence_id"]: e for e in state["evidence"]}
    claims = [
        c["metadata"]["claim"]
        for c in receipt["response"]["citations"]
        if c["type"] == "verified_claim"
    ]
    assert len(claims) == len(expected["metrics"]) * len(expected["selected_game_ids"])
    assert {c["metric_id"] for c in claims} == set(expected["metrics"])
    for claim in claims:
        assert claim == native[claim["claim_id"]]
        assert len(claim["game_ids"]) == 1 and claim["sample_size"] == 1
        game_id = claim["game_ids"][0]
        assert game_id in expected["selected_game_ids"]
        assert claim["value"] == (
            expected["margin"]
            if claim["metric_id"] == "margin"
            else expected["scores"][str(game_id)]
        )
        comparison = claim["eligibility"]["comparison"]
        assert sorted(comparison["game_ids"]) == expected["comparison_game_ids"]
        assert sorted(comparison["selected_game_ids"]) == expected["selected_game_ids"]
        assert comparison["sample_size"] == len(expected["comparison_game_ids"])
        for ref in claim["supporting_evidence_ids"]:
            calculation = evidence[ref]
            refs = calculation["metadata"]["source_evidence_ids"]
            assert len(refs) == len(set(refs)) == len(expected["comparison_game_ids"])
            assert set(refs) == {
                f"{claim['release_id']}:game:{g}" for g in expected["comparison_game_ids"]
            }
    for entry in receipt["model_inputs"]:
        payload = entry["user"]
        restored_claims = analyst_loop.payload_claims(payload)
        restored_evidence = {e["evidence_id"]: e for e in analyst_loop.payload_evidence(payload)}
        for claim in restored_claims:
            assert claim == native[claim["claim_id"]]
        for key, item in restored_evidence.items():
            assert item == receipt["native_registry"][key]
        if payload["schema"]["title"] == "AnswerReview":
            proposed = analyst_loop.payload_proposed_answer(payload)
            assert proposed is not None
            assert proposed["evidence_ids"]
            assert set(proposed["evidence_ids"]) <= restored_evidence.keys()
            assert set(native) == {c["claim_id"] for c in restored_claims}


@pytest.mark.parametrize(
    "behavior", ["exact-stopped", "false-margin", "tied", "long-supported", "highest", "lowest"]
)
async def test_largest_win_review_socket_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    behavior,  # noqa: F811
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    expected, text = await source_archive(tmp_path, behavior)
    adapter = LargestWinAdapter(text, behavior)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    original_payload, original_model = (
        analyst_loop.AnalystLoop.payload,
        analyst_loop.AnalystLoop.model,
    )
    failures = []
    native_registry = {}

    def observe_payload(self, schema, **kwargs):
        native_registry.update(
            {key: value.model_dump(mode="json") for key, value in self.tools.evidence.items()}
        )
        try:
            return original_payload(self, schema, **kwargs)
        except Exception as exc:
            failures.append(
                {
                    "boundary": "payload",
                    "schema": schema.__name__,
                    "review": kwargs.get("review", False),
                    "exception": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            raise

    async def observe_model(self, schema, **kwargs):
        try:
            return await original_model(self, schema, **kwargs)
        except Exception as exc:
            failures.append(
                {
                    "boundary": "model",
                    "schema": schema.__name__,
                    "review": kwargs.get("review", False),
                    "exception": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            raise

    monkeypatch.setattr(analyst_loop.AnalystLoop, "payload", observe_payload)
    monkeypatch.setattr(analyst_loop.AnalystLoop, "model", observe_model)
    receipt = await record_exchange(
        client,
        local_redis,
        adapter,
        f"What was the Knicks {behavior} scoring game?"
        if behavior in {"highest", "lowest"}
        else QUESTION,
        "largest-win-" + behavior,
    )
    receipt.update(
        expected=expected,
        scripted_text=text,
        preparation_exceptions=failures,
        native_registry=native_registry,
        archive_sha256=expected["archive_sha256"],
    )
    save_receipt(tmp_path, record_property, "largest-win-" + behavior, receipt)
    assert_committed_replay(receipt)
    assert settings.analyst_input_tokens == 8000 and settings.analyst_evidence_tokens == 6000
    assert settings.analyst_max_model_calls == 6 and settings.analyst_max_tool_rounds == 2
    assert receipt["real_provider_requests"] == 0
    assert all(item["schema_valid"] and item["input_bytes"] <= 8000 for item in adapter.inputs)
    verify_native(receipt, expected)
    assert not failures, failures
    if behavior == "false-margin":
        assert receipt["response"]["llm_validated"] is False
        assert receipt["response"]["answer"] != text
        assert receipt["response"]["route"] == "factual_fallback"
    else:
        assert receipt["response"]["llm_validated"] is True
        assert receipt["response"]["answer"] == text
        assert receipt["response"]["follow_up_questions"] == adapter.follow_ups
