"""Final-review calculation eligibility through HTTP, SQL and isolated Redis."""

import gzip
import json
from copy import deepcopy

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.game import Game
from app.services import analyst_loop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import (
    AnswerReview,
    Evidence,
    ProposedAnswer,
    VerifiedClaim,
    validate_review,
)
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import (
    SyntheticAdapter,
    assert_committed_replay,
    configure,
    exchange,
    save_receipt,
)
from app.tests.test_canonical_narrative_http import BUNDLE, SHA, request
from app.tests.test_player_intelligence import _seed_release_stats
from jsonschema import Draft202012Validator
from sqlalchemy import select


async def test_prior_shooting_cannot_answer_current_record(client, local_redis, monkeypatch):  # noqa: F811
    configure(monkeypatch)
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    adapter = SyntheticAdapter(
        {
            "name": "get_team_stats",
            "question": "Compare the Knicks shooting percentage in January and February.",
        }
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    first = await exchange(
        client,
        local_redis,
        adapter,
        "prior-month-shooting",
        "Compare the Knicks shooting percentage in January and February.",
    )
    previous = first["response"]
    assert previous["citations"]

    class Unavailable:
        async def generate(self, **kwargs):
            raise RuntimeError("Isolated provider failure")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", Unavailable)
    response = await client.post(
        "/analysis/query",
        json={
            "question": "Compare the Knicks record in January and February.",
            "turn_id": "current-month-record",
            "session_token": previous["session_token"],
            "expected_revision": previous["revision"],
        },
    )
    assert response.status_code == 200
    claims = [c["metadata"]["claim"] for c in response.json()["citations"]]
    assert {c["window"]["comparison_group"] for c in claims} == {"January", "February"}
    assert all(set(c["value"]) == {"games", "wins", "losses"} for c in claims)


async def test_march_recent_comparison_has_full_season_operand(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = {g["nba_game_id"]: g for g in raw["games"]}
    rows = sorted(
        [s for s in raw["player_game_stats"] if s["nba_player_id"] == 1628973 and s["minutes"] > 0],
        key=lambda s: (games[s["nba_game_id"]]["game_date"], s["nba_game_id"]),
    )
    march = [s for s in rows if games[s["nba_game_id"]]["game_date"].startswith("2026-03")][-5:]
    assert march and len(rows) > len(march)
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        ids = {g.nba_game_id: g.id for g in (await db.execute(select(Game))).scalars()}
    body, _ = await request(
        client,
        local_redis,
        monkeypatch,
        tmp_path,
        "march-season",
        "Compare Brunson's last 5 games in March with his season average.",
    )
    claims = list(
        {
            c["metadata"]["claim"]["claim_id"]: c["metadata"]["claim"] for c in body["citations"]
        }.values()
    )
    for population in (march, rows):
        matched = [
            c
            for c in claims
            if c["metric_id"] == "points:average"
            and set(c["game_ids"]) == {ids[s["nba_game_id"]] for s in population}
        ]
        assert len(matched) == 1
        assert matched[0]["value"] == pytest.approx(
            sum(s["points"] for s in population) / len(population)
        )


@pytest.mark.parametrize(
    "question,omit,tied_count",
    [
        ("What was the Knicks highest-scoring game?", False, 2),
        ("What was the Knicks biggest win by margin?", False, 1),
        ("What was the Knicks highest-scoring game?", True, 2),
        ("What was the Knicks biggest win by margin?", True, 1),
        ("What was the Knicks biggest win by margin?", False, 2),
        ("What was the Knicks biggest win by margin?", False, 12),
    ],
)
async def test_primary_scalar_extrema_complete_selected_set(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    question,
    omit,
    tied_count,
):
    configure(monkeypatch)
    async with AsyncSessionLocal() as db:
        loaded = await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        games = (
            (
                await db.execute(
                    select(Game)
                    .where(
                        Game.release_id == loaded.release_id,
                        Game.home_team_id == "NYK",
                        Game.status == "final",
                    )
                    .order_by(Game.game_date, Game.nba_game_id)
                )
            )
            .scalars()
            .all()
        )
        # Both selection and scalar receipts read these active-release Game scores.
        # Do not mutate unrelated preexisting releases supplied by the client fixture.
        for game in games[:tied_count]:
            game.home_score, game.away_score = 250, 50
        await db.commit()

    class ExtremaAdapter(SyntheticAdapter):
        async def generate(self, *, system, user):
            payload = json.loads(user)
            result = analyst_loop.decode_model_response(
                payload, json.loads(await super().generate(system=system, user=user))
            )
            answer = (
                result.get("answer")
                if payload["schema"]["title"] == "Action"
                else result
                if payload["schema"]["title"] == "ProposedAnswer"
                else None
            )
            if omit and answer:
                answer["claims"] = answer["claims"][:-1]
                ids = {c["claim_id"] for c in answer["claims"]}
                answer["text"] = " ".join(
                    c["statement"]
                    for c in analyst_loop.payload_claims(payload)
                    if c["claim_id"] in ids
                )
            return json.dumps(analyst_loop.encode_model_response(payload, result))

    adapter = ExtremaAdapter({"name": "get_game_narrative", "question": question})
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(
        client,
        local_redis,
        adapter,
        f"extreme-{omit}-{tied_count}-{'margin' if 'margin' in question else 'score'}",
        question,
    )
    body = receipt["response"]
    assert receipt["status"] == 200
    if tied_count == 1 or "margin" not in question:
        assert body["llm_validated"] is (not omit)
    claims = [c["metadata"]["claim"] for c in body["citations"]]
    expected_metrics = {"game_score", "margin"} if "margin" in question else {"game_score"}
    required = {(metric, g.id) for metric in expected_metrics for g in games[:tied_count]}
    assert {(c["metric_id"], c["game_ids"][0]) for c in claims} == required


class RequiredSlotsAdapter(SyntheticAdapter):
    """Exercise the actual writer wire; malformed selections are never re-encoded."""

    response_schema = None

    def __init__(self, question, behavior="complete", precision=None):
        super().__init__({"name": "get_team_stats", "question": question})
        self.behavior, self.precision = behavior, precision
        self.outputs = []
        self.decoded = []
        self.review_decisions = []

    async def generate(self, *, system, user):
        payload = json.loads(user)
        if payload["schema"]["title"] == "AnswerReview":
            assert "required_claim_indexes" not in payload
            assert "related_claim_indexes" not in payload
            declared = analyst_loop.payload_proposed_answer(payload)
            assert declared == self.decoded[-1]
            raw = await super().generate(system=system, user=user)
            self.inputs[-1]["response_schema"] = deepcopy(self.response_schema)
            self.inputs[-1]["input_bytes"] += len(
                analyst_loop.encoded(self.response_schema).encode()
            )
            review = analyst_loop.decode_model_response(payload, json.loads(raw))
            claims = {
                claim["claim_id"]: VerifiedClaim.model_validate(claim)
                for claim in analyst_loop.payload_claims(payload)
            }
            evidence = {
                item["evidence_id"]: Evidence.model_validate(item)
                for item in analyst_loop.payload_evidence(payload)
            }
            native_answer = ProposedAnswer.model_validate(declared)
            original = deepcopy(review)
            undeclared_support = {
                claim_id
                for assertion in review["assertions"]
                for claim_id in assertion["supporting_claim_ids"]
            } - {use.claim_id for use in native_answer.claims}
            original_valid = validate_review(
                AnswerReview.model_validate(original), native_answer, claims, evidence
            )
            assert original_valid is (not undeclared_support)
            # Atomic context can contain unselected alternatives. A scripted
            # valid review must support the actual declared uses, not every
            # admitted context ID; the native reviewer validator is unchanged.
            for assertion in review["assertions"]:
                assertion["supporting_claim_ids"] = [use.claim_id for use in native_answer.claims]
            assert validate_review(
                AnswerReview.model_validate(review), native_answer, claims, evidence
            )
            self.review_decisions.append(
                {
                    "original_scripted_review": original,
                    "original_support_validation": original_valid,
                    "undeclared_support_ids": sorted(undeclared_support),
                    "returned_scripted_review": review,
                }
            )
            return json.dumps(analyst_loop.encode_model_response(payload, review))
        if not analyst_loop.payload_claims(payload):
            return await super().generate(system=system, user=user)
        assert self.response_schema is not None
        claims = analyst_loop.payload_claims(payload)
        self.inputs.append(
            {
                "system": system,
                "user": payload,
                "response_schema": deepcopy(self.response_schema),
                "input_bytes": len((system + user).encode())
                + len(analyst_loop.encoded(self.response_schema).encode()),
            }
        )
        groups = payload["required_claim_indexes"]
        assert set(self.response_schema["required"]) == set(self.response_schema["properties"])
        slots = self.response_schema["properties"]["claims"]
        assert slots["additionalProperties"] is False
        assert set(slots["required"]) == set(slots["properties"])
        assert all(slot["type"] == "integer" for slot in slots["properties"].values())
        selections = {}
        for ordinal, domain in enumerate(groups):
            claim_index = domain[-1]
            precision = (
                self.precision if type(claims[claim_index]["value"]) in (int, float) else None
            )
            selections[str(ordinal)] = payload["claim_uses"].index([claim_index, precision])
        native = {
            "text": " ".join(claims[domain[-1]]["statement"] for domain in groups),
            "claims": [
                {
                    "claim_id": claims[payload["claim_uses"][choice][0]]["claim_id"],
                    "displayed_value": (
                        round(claims[payload["claim_uses"][choice][0]]["value"], precision)
                        if (precision := payload["claim_uses"][choice][1]) is not None
                        else claims[payload["claim_uses"][choice][0]]["value"]
                    ),
                    "decimal_places": precision,
                }
                for choice in selections.values()
            ],
            "evidence_ids": [],
            "fact_ids": [],
            "follow_up_questions": [],
        }
        wire = {**native, "claims": selections}
        if payload.get("related_claim_indexes"):
            wire["related_claims"] = []
        if self.behavior == "complete":
            Draft202012Validator(self.response_schema).validate(wire)
            assert analyst_loop.encode_model_response(payload, native) == wire
            restored = analyst_loop.decode_model_response(payload, wire)
            assert restored == native
            self.decoded.append(restored)
        else:
            score_slot = next(
                str(ordinal)
                for ordinal, domain in enumerate(groups)
                if claims[domain[0]]["metric_id"] == "game_score"
            )
            margin_choice = next(
                choice
                for choice in selections.values()
                if claims[payload["claim_uses"][choice][0]]["metric_id"] == "margin"
            )
            if self.behavior == "old-two-margins":
                margin = next(use for use in native["claims"] if use["displayed_value"] == -38)
                wire["claims"] = [margin, {**margin, "decimal_places": 0}]
                assert analyst_loop.encode_model_response(payload, wire) == wire
            elif self.behavior == "omitted-score":
                del wire["claims"][score_slot]
            elif self.behavior == "wrong-slot":
                wire["claims"][score_slot] = margin_choice
            elif self.behavior == "bool":
                wire["claims"][score_slot] = True
            elif self.behavior == "float":
                wire["claims"][score_slot] = float(wire["claims"][score_slot])
            elif self.behavior == "string":
                wire["claims"][score_slot] = str(wire["claims"][score_slot])
            elif self.behavior == "invented":
                wire["claims"][score_slot] = len(payload["claim_uses"])
            elif self.behavior == "extra-slot":
                wire["claims"]["invented"] = margin_choice
            elif self.behavior == "required-related":
                wire["related_claims"] = [margin_choice]
            elif self.behavior == "object-precision":
                bad = deepcopy(native)
                next(use for use in bad["claims"] if isinstance(use["displayed_value"], dict))[
                    "decimal_places"
                ] = 0
                wire = analyst_loop.encode_model_response(payload, bad)
                assert wire == bad, "Invalid native fixtures must not be repaired by encoding"
            elif self.behavior == "duplicate-key":
                raw = json.dumps(wire)
                raw = raw.replace(
                    '"claims": {', f'"claims": {{"{score_slot}": {margin_choice}, ', 1
                )
                self.outputs.append(raw)
                return raw
            else:
                raise AssertionError(self.behavior)
            # JSON Schema treats an integral float as an integer; the native
            # decoder must additionally reject its actual Python/JSON type.
            if self.behavior != "float":
                assert not Draft202012Validator(self.response_schema).is_valid(wire)
        self.outputs.append(wire)
        return json.dumps(wire)


async def seed_required_score():
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        games = (
            (await db.execute(select(Game).where(Game.release_id == release.id).order_by(Game.id)))
            .scalars()
            .all()
        )
        for game in games:
            game.home_team_id, game.away_team_id = "NYK", "DET"
            game.home_score, game.away_score = 110, 100
        games[0].home_score, games[0].away_score = 80, 118
        await db.commit()
        return games[0].id


@pytest.mark.parametrize("precision", [None, 0, 1, 2, 3])
async def test_required_score_margin_choice_reaches_independent_review_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    precision,
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    selected_game = await seed_required_score()
    question = "What was the Knicks worst loss by margin?"
    adapter = RequiredSlotsAdapter(question, precision=precision)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, f"required-score-{precision}", question)
    save_receipt(tmp_path, record_property, f"required-score-{precision}", receipt)
    assert_committed_replay(receipt)
    assert receipt["response"]["llm_validated"]
    assert [item["user"]["schema"]["title"] for item in adapter.inputs] == [
        "ProposedAnswer",
        "AnswerReview",
    ]
    delivered = {
        c["metadata"]["claim"]["metric_id"]: c["metadata"]["claim"]
        for c in receipt["response"]["citations"]
    }
    assert delivered["game_score"]["value"] == {"NYK": 80, "DET": 118}
    assert delivered["margin"]["value"] == -38
    assert all(c["game_ids"] == [selected_game] for c in delivered.values())
    assert all(item["input_bytes"] <= 8000 for item in adapter.inputs)
    assert not any("related_claims" in output for output in adapter.outputs)
    assert (
        next(
            use["decimal_places"]
            for use in adapter.decoded[0]["claims"]
            if use["displayed_value"] == -38
        )
        == precision
    )


@pytest.mark.parametrize(
    "behavior",
    [
        "old-two-margins",
        "omitted-score",
        "wrong-slot",
        "bool",
        "float",
        "string",
        "invented",
        "extra-slot",
        "required-related",
        "object-precision",
        "duplicate-key",
    ],
)
async def test_required_claim_wire_rejects_without_autofill_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    behavior,
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    await seed_required_score()
    question = "What was the Knicks worst loss by margin?"
    adapter = RequiredSlotsAdapter(question, behavior)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, f"required-reject-{behavior}", question)
    receipt["raw_scripted_outputs"] = adapter.outputs
    save_receipt(tmp_path, record_property, f"required-reject-{behavior}", receipt)
    assert_committed_replay(receipt)
    assert not receipt["response"]["llm_validated"]
    assert len(adapter.inputs) == 1, "Malformed wire must not reach repair or independent review"
    assert not adapter.decoded
    delivered = {c["metadata"]["claim"]["metric_id"] for c in receipt["response"]["citations"]}
    assert delivered == {"game_score", "margin"}, "Complete fallback is not a model pass"


async def test_required_slots_leave_related_context_optional_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    await seed_required_score()
    execute = AnalystTools.execute

    async def optional_context(self, call):
        result = await execute(self, call)
        if call.name == "get_team_stats" and result.claims:
            optional = result.claims[0].model_copy(
                update={"claim_id": "synthetic:optional-context", "metric_id": "optional_context"}
            )
            self.claims[optional.claim_id] = optional
            result = result.model_copy(update={"claims": [*result.claims, optional]})
        return result

    monkeypatch.setattr(AnalystTools, "execute", optional_context)
    question = "What was the Knicks record over their last 3 games?"
    adapter = RequiredSlotsAdapter(question)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, "required-optional-context", question)
    assert_committed_replay(receipt)
    assert receipt["response"]["llm_validated"]
    writer = next(
        item["user"] for item in adapter.inputs if "required_claim_indexes" in item["user"]
    )
    supplied = analyst_loop.payload_claims(writer)
    optional_index = next(
        index
        for index, claim in enumerate(supplied)
        if claim["claim_id"] == "synthetic:optional-context"
    )
    assert writer["related_claim_indexes"] == [optional_index]
    assert all(optional_index not in domain for domain in writer["required_claim_indexes"])
    assert adapter.outputs[-1]["related_claims"] == []
    assert all(
        c["metadata"]["claim"]["claim_id"] != "synthetic:optional-context"
        for c in receipt["response"]["citations"]
    )


async def test_required_slots_preserve_same_pair_alternatives_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    await seed_required_score()
    execute = AnalystTools.execute

    async def alternate_margin(self, call):
        result = await execute(self, call)
        if call.name == "get_game_narrative":
            margin = next(claim for claim in result.claims if claim.metric_id == "margin")
            alternative = margin.model_copy(update={"claim_id": "synthetic:alternate-margin"})
            self.claims[alternative.claim_id] = alternative
            result = result.model_copy(update={"claims": [*result.claims, alternative]})
        return result

    monkeypatch.setattr(AnalystTools, "execute", alternate_margin)
    question = "What was the Knicks worst loss by margin?"
    adapter = RequiredSlotsAdapter(question)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    validate = analyst_loop.AnalystLoop.validate
    validations = []

    async def retain_native_validation(self, answer, **kwargs):
        supported, reason = await validate(self, answer, **kwargs)
        validations.append(
            {
                "decoded_answer": answer.model_dump(mode="json"),
                "native_requirements": {
                    policy: [sorted(domain) for domain in domains]
                    for policy, domains in self._required_claim_groups().items()
                },
                "sent_claim_ids": sorted(self.sent_claims),
                "supported": supported,
                "reason": reason,
            }
        )
        return supported, reason

    monkeypatch.setattr(analyst_loop.AnalystLoop, "validate", retain_native_validation)
    receipt = await exchange(client, local_redis, adapter, "required-pair-alternative", question)
    receipt["native_validations"] = validations
    receipt["scripted_review_decisions"] = adapter.review_decisions
    save_receipt(tmp_path, record_property, "required-pair-alternative", receipt)
    assert_committed_replay(receipt)
    assert receipt["response"]["llm_validated"]
    writer = adapter.inputs[0]["user"]
    assert sorted(map(len, writer["required_claim_indexes"])) == [1, 2]
    assert len(validations) == 1 and validations[0]["supported"]
    assert validations[0]["reason"] == ""
    decision = adapter.review_decisions[0]
    assert decision["undeclared_support_ids"]
    assert decision["original_support_validation"] is False
    assert "synthetic:alternate-margin" not in decision["undeclared_support_ids"]
    assert any(
        c["metadata"]["claim"]["claim_id"] == "synthetic:alternate-margin"
        for c in receipt["response"]["citations"]
    )


async def test_required_slot_repair_retains_original_bad_selection_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    await seed_required_score()
    question = "What was the Knicks worst loss by margin?"
    adapter = RequiredSlotsAdapter(question)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    model = analyst_loop.AnalystLoop.model
    original_bad = []

    async def historical_native_selection(self, schema, **kwargs):
        answer = await model(self, schema, **kwargs)
        if schema is ProposedAnswer and not kwargs.get("repair"):
            # A previously accepted native proposal can still be carried into a
            # repair. The current malformed-wire tests above never use this seam.
            margin = next(use for use in answer.claims if use.displayed_value == -38)
            answer = answer.model_copy(
                update={"claims": [margin, margin.model_copy(update={"decimal_places": 0})]}
            )
            original_bad.append(answer.model_dump(mode="json"))
        return answer

    monkeypatch.setattr(analyst_loop.AnalystLoop, "model", historical_native_selection)
    receipt = await exchange(client, local_redis, adapter, "required-bad-repair", question)
    assert_committed_replay(receipt)
    assert receipt["response"]["llm_validated"]
    repair = next(item["user"] for item in adapter.inputs if item["user"].get("repair"))
    assert analyst_loop.payload_proposed_answer(repair) == original_bad[0]
    assert len(repair["proposed_answer"]["claim_uses"]) == 2
    assert (
        repair["proposed_answer"]["claim_uses"][0][0]
        == repair["proposed_answer"]["claim_uses"][1][0]
    )
