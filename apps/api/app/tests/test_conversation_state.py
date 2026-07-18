"""Structured follow-up state behavior."""

from __future__ import annotations

from app.services.conversation_state import (
    ConversationState,
    resolve_conversation_delta,
)
from app.services.query_resolution import ResolvedQuery


def _resolved(**updates) -> ResolvedQuery:
    values = {
        "intent": "narrative",
        "data_version": "v1",
    }
    values.update(updates)
    return ResolvedQuery(**values)


def test_follow_up_inherits_entities_and_changes_only_explicit_metric():
    prior = ConversationState(
        player_ids=[11],
        game_ids=[7],
        opponent_id="BOS",
        metric="points",
        route="player_stat",
        data_version="v1",
    )

    resolved, state = resolve_conversation_delta(
        "What about rebounds?",
        _resolved(intent="player_stat", metric="rebounds"),
        prior,
    )

    assert resolved.player_ids == [11]
    assert resolved.game_ids == [7]
    assert resolved.opponent_id == "BOS"
    assert resolved.metric == "rebounds"
    assert state.player_ids == [11]
    assert state.metric == "rebounds"


def test_explicit_topic_change_does_not_leak_prior_filters():
    prior = ConversationState(
        player_ids=[11],
        game_ids=[7],
        opponent_id="BOS",
        metric="points",
        data_version="v1",
    )

    resolved, state = resolve_conversation_delta(
        "How did Karl-Anthony Towns play against Toronto?",
        _resolved(
            player_ids=[32],
            game_ids=[9],
            team_ids=["TOR"],
            opponent_id="TOR",
            metric="points",
        ),
        prior,
    )

    assert resolved.player_ids == [32]
    assert resolved.game_ids == [9]
    assert resolved.opponent_id == "TOR"
    assert state.player_ids == [32]


def test_ambiguous_pronoun_requests_clarification():
    prior = ConversationState(
        player_ids=[11, 12],
        metric="points",
        data_version="v1",
    )

    resolved, _state = resolve_conversation_delta(
        "What about his rebounds?",
        _resolved(metric="rebounds"),
        prior,
    )

    assert resolved.requires_clarification is True
    assert resolved.clarification_reason == "ambiguous_conversation_reference"
    assert resolved.clarification_options == ["player:11", "player:12"]


def test_equivalent_standalone_and_follow_up_resolve_to_same_filters():
    prior = ConversationState(
        player_ids=[11],
        game_ids=[7],
        opponent_id="BOS",
        data_version="v1",
    )
    follow_up, _state = resolve_conversation_delta(
        "What about his assists?",
        _resolved(metric="assists"),
        prior,
    )
    standalone = _resolved(
        player_ids=[11],
        game_ids=[7],
        team_ids=["BOS"],
        opponent_id="BOS",
        metric="assists",
    )

    assert follow_up.planner_filters() == standalone.planner_filters()
