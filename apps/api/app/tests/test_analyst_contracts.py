"""Analyst sessions, budgets, scope and evidence validation contracts."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from app.core.config import get_settings
from app.services.analyst_budget import BudgetReservation
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_sessions import SessionConflict, SessionTurn
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import (
    AnswerReview,
    AssertionReview,
    ClaimUse,
    ProposedAnswer,
    ToolCall,
    validate_review,
    validate_structure,
)
from app.tests.support.analyst_protocol import (
    local_redis as local_redis,
)
from app.tests.support.analyst_protocol import (
    make_tools,
)


async def test_session_race_replay_conflict_and_atomic_commit(local_redis):
    turn_id = "first-turn-identity"
    first = await SessionTurn.begin(None, turn_id, 0, {"question": "stat"})
    with pytest.raises(SessionConflict):
        await SessionTurn.begin(first.token, "second-turn-identity", 0, {"question": "stat"})
    assert (
        await first.commit({"answer": "Committed"}, {"delivered_fact_ids": ["fact:1"]})
    ).committed
    replay = await SessionTurn.begin(None, turn_id, 0, {"question": "stat"})
    assert replay.replay == {"answer": "Committed"}
    with pytest.raises(SessionConflict):
        await SessionTurn.begin(first.token, turn_id, 0, {"question": "changed"})
    with pytest.raises(SessionConflict):
        await SessionTurn.begin(first.token, "new-turn-identity", 0, {"question": "stat"})
    next_turn = await SessionTurn.begin(first.token, "new-turn-identity", 1, {"question": "stat"})
    assert next_turn.state["delivered_fact_ids"] == ["fact:1"]
    # The lease serializes turns, not commits: one that expired while the turn was still
    # working must not discard the completed answer. The revision this turn read is still
    # current, so the commit wins atomically.
    await local_redis.delete(next_turn.key + ":lease")
    assert (
        await next_turn.commit({"answer": "Finished late"}, {"delivered_fact_ids": ["fact:2"]})
    ).committed
    # A reply lost after the commit must not report the same turn as uncommitted.
    assert (
        await next_turn.commit({"answer": "Finished late"}, {"delivered_fact_ids": ["fact:2"]})
    ).committed
    assert json.loads(await local_redis.hget(first.key, "state"))["delivered_fact_ids"] == [
        "fact:2"
    ]
    assert 86000 < await local_redis.ttl(first.key) <= 86400
    # A different owner holding the lease is a competing turn; its commit stands alone.
    held = await SessionTurn.begin(first.token, "held-turn", 2, {"question": "stat"})
    await local_redis.set(held.key + ":lease", "another-owner", ex=35)
    assert not (await held.commit({"answer": "Raced"}, {"delivered_fact_ids": ["bad"]})).committed
    assert json.loads(await local_redis.hget(first.key, "state"))["delivered_fact_ids"] == [
        "fact:2"
    ]
    await local_redis.delete(first.key)
    with pytest.raises(SessionConflict) as expired:
        await SessionTurn.begin(first.token, "expired-turn-identity", 1, {"question": "stat"})
    assert expired.value.reason == "session_expired"


async def test_atomic_budget_starts_a_missing_month_at_zero(local_redis, monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_monthly_cutoff_usd", 0.08)
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    assert await local_redis.get(key) is None
    attempts = await asyncio.gather(*[BudgetReservation.reserve(0.02) for _ in range(12)])
    accepted = [r for r in attempts if r is not None]
    assert len(accepted) == 4
    assert float(await local_redis.get(key)) == pytest.approx(0.08)
    await accepted[0].settle(None)
    assert float(await local_redis.get(key)) == pytest.approx(0.08)
    await accepted[0].settle(0.005)
    await accepted[0].settle(0)
    assert float(await local_redis.get(key)) == pytest.approx(0.065)
    await local_redis.delete(key)
    assert await BudgetReservation.reserve(0.001) is not None


async def test_populations_and_scope_cannot_be_changed_by_model(db_session):
    tools, player = await make_tools(db_session, "Brunson regular season points")
    result = await tools.execute(ToolCall(name="get_player_stats", question="Towns playoffs"))
    assert result.status == "ok"
    claim = result.claims[0]
    assert claim.subject_id == f"player:{player.id}"
    assert claim.value == 25 and claim.denominator == 2 and claim.sample_size == 2
    assert claim.season_type == "regular"
    assert claim.game_ids is not None
    assert len(claim.game_ids) == 2
    answer = ProposedAnswer(
        text=claim.statement, claims=[ClaimUse(claim_id=claim.claim_id, displayed_value=25)]
    )
    assert validate_structure(answer, tools.claims, tools.evidence, {}, tools.release.version)
    wrong = answer.model_copy(
        update={"claims": [ClaimUse(claim_id=claim.claim_id, displayed_value=-25)]}
    )
    assert not validate_structure(wrong, tools.claims, tools.evidence, {}, tools.release.version)
    assert not validate_structure(answer, tools.claims, tools.evidence, {}, "other-release")


async def test_discovery_novelty_phase_and_complete_claim_records(db_session):
    tools, _ = await make_tools(db_session)
    result = await tools.execute(ToolCall(name="discover_facts", question=tools.question))
    candidate = result.candidates[0]
    assert len(result.candidates) <= 10
    assert candidate.extreme_selected
    assert all(c.sample_size == 1 for c in result.claims)
    state = {
        "release": tools.release.version,
        "delivered_fact_ids": [candidate.fact_id],
        "last_subjects": [candidate.subject_id],
        "scope": {},
    }
    next_tools = AnalystTools(
        db_session,
        tools.release,
        "Another one, but about a different player",
        tools.release.season,
        state,
    )
    await next_tools.prepare()
    second = await next_tools.execute(ToolCall(name="discover_facts", question=next_tools.question))
    assert second.candidates
    assert all(c.subject_id != candidate.subject_id for c in second.candidates)
    assert all(c.fact_id != candidate.fact_id for c in second.candidates)
    playoffs = AnalystTools(
        db_session, tools.release, "Now only playoff games", tools.release.season, state
    )
    await playoffs.prepare()
    result = await playoffs.execute(ToolCall(name="discover_facts", question="all games"))
    assert result.status == "no_matching_results" and not result.claims


@pytest.mark.parametrize(
    "change", ["hidden_intro", "missing_coverage", "unknown_reference", "bad_verdict"]
)
async def test_full_answer_review_fails_closed(db_session, change):
    tools, _ = await make_tools(db_session, "Brunson points")
    result = await tools.execute(ToolCall(name="get_player_stats", question=tools.question))
    claim = result.claims[0]
    answer = ProposedAnswer(
        text=claim.statement,
        claims=[ClaimUse(claim_id=claim.claim_id, displayed_value=claim.value)],
    )
    assertion = AssertionReview(
        text=answer.text,
        verdict="supported",
        assertion_type="factual",
        offending_text=None,
        supporting_claim_ids=[claim.claim_id],
        supporting_evidence_ids=[],
        reason="Exact backend calculation.",
    )
    review = AnswerReview(assertions=[assertion])
    assert validate_review(review, answer, tools.claims, tools.evidence)
    if change == "hidden_intro":
        answer = answer.model_copy(update={"text": "His new tactics worked. " + answer.text})
    elif change == "missing_coverage":
        review = AnswerReview(assertions=[assertion.model_copy(update={"text": answer.text[:-1]})])
    elif change == "unknown_reference":
        review = AnswerReview(
            assertions=[assertion.model_copy(update={"supporting_claim_ids": ["x"]})]
        )
    else:
        review = AnswerReview(assertions=[assertion.model_copy(update={"verdict": "unknown"})])
    assert not validate_review(review, answer, tools.claims, tools.evidence)


async def test_individual_absence_is_not_coverage_but_a_whole_game_is(db_session):
    from app.models.box_score import PlayerGameStat
    from sqlalchemy import delete

    tools, player = await make_tools(db_session, "Brunson points")
    absent = next(s for s, p in tools.rows if p.id == player.id and s.minutes == 0)
    await db_session.execute(delete(PlayerGameStat).where(PlayerGameStat.id == absent.id))
    await db_session.flush()
    current = AnalystTools(db_session, tools.release, tools.question, tools.season, {})
    await current.prepare()
    result = await current.execute(ToolCall(name="get_player_stats", question=tools.question))
    # Other NYK rows exist for that game, so the player did not appear; that is not a gap.
    assert result.status == "ok"
    assert result.claims[0].sample_size == 2 and result.claims[0].value == 25
    assert "did not appear" in " ".join(result.claims[0].coverage_limitations)
    # Deleting every NYK row for a game leaves genuinely unknown coverage.
    await db_session.execute(
        delete(PlayerGameStat).where(
            PlayerGameStat.game_id == absent.game_id, PlayerGameStat.team_id == "NYK"
        )
    )
    await db_session.flush()
    current = AnalystTools(db_session, tools.release, tools.question, tools.season, {})
    await current.prepare()
    result = await current.execute(ToolCall(name="get_player_stats", question=tools.question))
    assert result.status == "incomplete_coverage"
    assert "No player rows at all" in " ".join(result.claims[0].coverage_limitations)


async def test_team_average_aggregation_yields_per_game_claims(db_session):
    tools, _ = await make_tools(db_session, "What were the Knicks points and margin?")
    totals = await tools.execute(
        ToolCall(name="get_team_stats", question=tools.question, aggregation="total")
    )
    averages = await tools.execute(
        ToolCall(name="get_team_stats", question=tools.question, aggregation="average")
    )
    by_metric = {c.metric_id: c for c in totals.claims}
    per_game = {c.metric_id: c for c in averages.claims}
    games = by_metric["points"].sample_size
    assert games and games > 0
    points, margin = by_metric["points"].value, by_metric["margin"].value
    assert isinstance(points, (int, float)) and isinstance(margin, (int, float))
    assert per_game["points_per_game"].value == pytest.approx(points / games)
    assert per_game["margin_per_game"].value == pytest.approx(margin / games)
    assert per_game["margin_per_game"].denominator == games
    assert {"wins", "losses"} <= per_game.keys()
    assert "points" not in per_game and "margin" not in per_game


async def test_unknown_entity_and_baseline_scope_fail_closed(db_session):
    tools, _ = await make_tools(db_session, "An interesting stat about Nobody McFake")
    result = await tools.execute(ToolCall(name="discover_facts", question="Brunson"))
    assert result.status == "ambiguous_entity" and not result.claims
    current = AnalystTools(db_session, tools.release, "Brunson points", tools.season, {})
    await current.prepare()
    result = await current.execute(
        ToolCall(
            name="compare_windows",
            question="Brunson points",
            baseline_question="2024-25 regular season",
        )
    )
    assert result.status == "unsupported_metric_or_scope" and not result.claims


async def test_whole_records_fit_budget_and_provenance_is_resolvable(db_session):
    tools, _ = await make_tools(db_session)
    result = await tools.execute(ToolCall(name="discover_facts", question=tools.question))
    loop = AnalystLoop(tools, [])
    loop.results.append(result)
    from app.services.analyst_provider import encoded, token_upper_bound
    from app.services.evidence_contracts import Action

    payload = loop.payload(Action)
    assert token_upper_bound(encoded(payload)) + 1700 <= get_settings().analyst_input_tokens
    assert payload["candidates"]
    for claim in payload["claims"]:
        full = tools.claims[claim["claim_id"]].model_dump(mode="json")
        assert {"game_ids", "release_id", "calculation_version"}.isdisjoint(claim)
        assert claim["value"] == full["value"] and claim["statement"] == full["statement"]
        assert claim["supporting_evidence_ids"] == full["supporting_evidence_ids"]
        assert all(full[k] == v for k, v in claim.items() if k != "filters")
        assert all(ref in tools.evidence for ref in claim["supporting_evidence_ids"])


async def test_review_spans_preserve_decimal_punctuation_and_full_coverage(db_session):
    tools, _ = await make_tools(db_session)
    loop = AnalystLoop(tools, [{"role": "user", "content": "Untrusted context"}])
    answer = ProposedAnswer(
        text="Ask about a 25.5-point average.  Why?\nAsk about archive games—only."
    )
    payload = loop.payload(AnswerReview, answer=answer, review=True)
    spans = payload["review_spans"]
    assert spans == ["Ask about a 25.5-point average.  ", "Why?\n", "Ask about archive games—only."]
    assert "context" not in payload
    review = AnswerReview(
        assertions=[
            AssertionReview(
                text=span,
                assertion_type="conversational",
                verdict="supported",
                offending_text=None,
                supporting_claim_ids=[],
                supporting_evidence_ids=[],
                reason="Format fixture.",
            )
            for span in spans
        ]
    )
    assert validate_review(review, answer, {}, {})
    truncated = review.model_copy(update={"assertions": review.assertions[:-1]})
    assert not validate_review(truncated, answer, {}, {})
    stripped = review.model_copy(
        update={
            "assertions": [a.model_copy(update={"text": a.text.strip()}) for a in review.assertions]
        }
    )
    assert not validate_review(stripped, answer, {}, {})


async def test_scoped_schema_rejects_invented_ids_and_partial_claim_values(db_session):
    from copy import deepcopy

    from app.services.analyst_provider import scoped_response_schema
    from app.services.evidence_contracts import Action
    from jsonschema import Draft202012Validator

    tools, _ = await make_tools(db_session)
    result = await tools.execute(ToolCall(name="discover_facts", question=tools.question))
    loop = AnalystLoop(tools, [])
    loop.results.append(result)
    payload = loop.payload(Action)
    claim = payload["claims"][0]
    candidate = next(c for c in payload["candidates"] if claim["claim_id"] in c["claim_ids"])
    answer = {
        "action": "answer_from_available_evidence",
        "tools": [],
        "answer": {
            "text": claim["statement"],
            "claims": [
                {
                    "claim_id": claim["claim_id"],
                    "displayed_value": claim["value"],
                    "decimal_places": None,
                }
            ],
            "evidence_ids": [],
            "fact_ids": [candidate["fact_id"]],
        },
    }
    validator = Draft202012Validator(scoped_response_schema(Action, payload))
    assert validator.is_valid(answer)
    wrong = deepcopy(answer)
    wrong["answer"]["claims"][0]["displayed_value"] = {"points": 47}
    assert not validator.is_valid(wrong)
    wrong = deepcopy(answer)
    wrong["answer"]["fact_ids"] = ["invented"]
    assert not validator.is_valid(wrong)
    # The ordinary schema remains reusable and is not mutated by release-scoping.
    assert "enum" not in Action.model_json_schema()["$defs"]["ClaimUse"]


async def test_catalog_preserves_baselines_and_qualifier_population(db_session, monkeypatch):
    from collections import Counter
    from datetime import date, timedelta

    from app.models.box_score import PlayerGameStat
    from app.models.game import Game
    from app.services import analyst_tools

    evidence_type = analyst_tools.Evidence
    constructed = Counter()

    def counted_evidence(**kwargs):
        constructed[kwargs["evidence_id"]] += 1
        return evidence_type(**kwargs)

    monkeypatch.setattr(analyst_tools, "Evidence", counted_evidence)

    tools, player = await make_tools(db_session)
    for i in range(14):
        game = Game(
            release_id=tools.release.id,
            nba_game_id=f"catalog-{i}",
            season=tools.season,
            game_date=date(2026, 2, 1) + timedelta(days=i),
            home_team_id="NYK",
            away_team_id="BOS",
            home_score=110,
            away_score=100,
            status="final",
            season_type="regular",
            source_name="fixture",
            source_game_id=f"catalog-{i}",
        )
        db_session.add(game)
        await db_session.flush()
        db_session.add(
            PlayerGameStat(
                release_id=tools.release.id,
                game_id=game.id,
                player_id=player.id,
                team_id="NYK",
                minutes=30,
                points=40 if i > 3 else 10,
                field_goals_attempted=20,
            )
        )
    await db_session.flush()
    tools = AnalystTools(
        db_session, tools.release, "Interesting stat about Brunson", tools.season, {}
    )
    await tools.prepare()
    result = await tools.execute(ToolCall(name="discover_facts", question=tools.question))
    assert result.status == "ok", result
    # Inspect all backend catalog claims, not just the bounded ten selected candidates.
    deltas = [c for c in tools.claims.values() if c.metric_id == "points:delta"]
    assert deltas
    delta = deltas[0]
    recent, prior = [tools.claims[ref] for ref in delta.baseline_claim_ids]
    assert recent.sample_size == 10 and prior.sample_size == 6
    assert isinstance(recent.value, (int, float)) and isinstance(prior.value, (int, float))
    assert delta.value == pytest.approx(recent.value - prior.value)
    assert recent.game_ids is not None and prior.game_ids is not None
    assert not set(recent.game_ids) & set(prior.game_ids)
    ranks = [c for c in tools.claims.values() if c.metric_id.endswith(":qualifier_rank")]
    assert ranks and all(c.eligibility["minimum_appearances"] == 4 for c in ranks)
    source_receipts = {key: count for key, count in constructed.items() if ":game:" in key}
    assert source_receipts and max(source_receipts.values()) == 1


def test_release_gates_require_actual_metrics_and_human_labels():
    from app.evaluation.analyst_evaluation import release_gates

    assert not any(release_gates({}).values())
    gates = release_gates(
        {
            "normal_llm_completion": 0.94,
            "unsupported_claims": 0,
            "reviewed_answers": 0,
            "unsupported_challenges_accepted": 0,
            "human_labelled_challenges": 0,
            "warm_ordinary_p95_ms": 15001,
        }
    )
    assert not gates["normal_llm_completion"]
    assert not gates["heldout_reviewer"]
    assert not gates["unsupported_claims"]
    assert not gates["latency"]
