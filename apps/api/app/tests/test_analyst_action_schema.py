"""Validate emitted Action schemas against sanitized real prerequisite exchanges."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from app.services.analyst_loop import scoped_response_schema
from app.services.evidence_contracts import (
    PLAYER_METRICS,
    TEAM_METRICS,
    Action,
    ProposedAnswer,
    ToolCall,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

CAPTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "analyst_action_schema_captures.json").read_text()
)
EMPTY_TOOL_ACTIONS = CAPTURES["empty_tool_actions"]
VALID_TOOL_ACTIONS = CAPTURES["valid_tool_actions"]
GROUNDED_ANSWER_ACTIONS = CAPTURES["valid_grounded_answer_actions"]
ANSWER_ACTIONS = ["answer_from_available_evidence", "ask_clarification", "explain_coverage"]


def capture_id(capture):
    return f"{capture['ticket']}-{capture['case_id']}"


def captured_action(capture):
    assert (
        hashlib.sha256(capture["content"].encode("utf-8")).hexdigest() == capture["content_sha256"]
    )
    return json.loads(capture["content"])


def emitted_validator(scope, schema=Action):
    emitted = scoped_response_schema(schema, scope)
    Draft202012Validator.check_schema(emitted)
    return Draft202012Validator(emitted)


def test_all_nine_failed_exchanges_are_retained():
    assert [(capture["ticket"], capture["case_id"]) for capture in EMPTY_TOOL_ACTIONS] == [
        (199, "date_range_last_n-008"),
        (202, "exact_statistics-002"),
        (203, "exact_statistics-004"),
        (210, "exact_statistics-013"),
        (211, "exact_statistics-015"),
        (217, "exact_statistics-017"),
        (218, "exact_statistics-018"),
        (223, "exact_statistics-021"),
        (224, "exact_statistics-025"),
    ]


@pytest.mark.parametrize("capture", EMPTY_TOOL_ACTIONS, ids=capture_id)
def test_emitted_schema_rejects_captured_empty_tool_actions(capture):
    action = captured_action(capture)
    assert not emitted_validator(capture["scope"]).is_valid(action)


@pytest.mark.parametrize("capture", VALID_TOOL_ACTIONS, ids=capture_id)
@pytest.mark.parametrize("omit_answer", [False, True], ids=["null-answer", "omitted-answer"])
def test_emitted_schema_admits_captured_tool_actions(capture, omit_answer):
    action = captured_action(capture)
    if omit_answer:
        del action["answer"]
    emitted_validator(capture["scope"]).validate(action)


@pytest.mark.parametrize("capture", GROUNDED_ANSWER_ACTIONS, ids=capture_id)
@pytest.mark.parametrize("action_name", ANSWER_ACTIONS)
@pytest.mark.parametrize("include_tools", [False, True], ids=["omitted-tools", "empty-tools"])
def test_emitted_schema_admits_grounded_answer_branches(capture, action_name, include_tools):
    action = captured_action(capture)
    action["action"] = action_name
    if include_tools:
        action["tools"] = []
    emitted_validator(capture["scope"]).validate(action)


@pytest.mark.parametrize("tools", [None, [], [{}]], ids=["null", "empty", "invalid-call"])
def test_tool_branch_requires_valid_nonempty_tools(tools):
    capture = VALID_TOOL_ACTIONS[0]
    action = captured_action(capture)
    action["tools"] = tools
    assert not emitted_validator(capture["scope"]).is_valid(action)


def test_tool_branch_requires_tools_property():
    capture = VALID_TOOL_ACTIONS[0]
    action = captured_action(capture)
    del action["tools"]
    assert not emitted_validator(capture["scope"]).is_valid(action)


def test_tool_branch_rejects_unknown_tool_and_excess_calls():
    capture = VALID_TOOL_ACTIONS[0]
    action = captured_action(capture)
    action["tools"][0]["name"] = "invented_tool"
    assert not emitted_validator(capture["scope"]).is_valid(action)
    action = captured_action(capture)
    action["tools"] *= 4
    assert not emitted_validator(capture["scope"]).is_valid(action)


@pytest.mark.parametrize("action_name", ["call_tools", *ANSWER_ACTIONS])
def test_all_branches_reject_simultaneous_answer_and_tools(action_name):
    capture = GROUNDED_ANSWER_ACTIONS[0]
    action = captured_action(capture)
    action["action"] = action_name
    action["tools"] = captured_action(VALID_TOOL_ACTIONS[0])["tools"]
    assert not emitted_validator(capture["scope"]).is_valid(action)


@pytest.mark.parametrize("action_name", ANSWER_ACTIONS)
@pytest.mark.parametrize("answer_state", ["missing", "null", "empty-object", "empty-text"])
def test_answer_branches_require_valid_answer(action_name, answer_state):
    capture = GROUNDED_ANSWER_ACTIONS[0]
    action = captured_action(capture)
    action["action"] = action_name
    if answer_state == "missing":
        del action["answer"]
    elif answer_state == "null":
        action["answer"] = None
    elif answer_state == "empty-object":
        action["answer"] = {}
    else:
        action["answer"]["text"] = ""
    assert not emitted_validator(capture["scope"]).is_valid(action)


@pytest.mark.parametrize("action_name", ANSWER_ACTIONS)
def test_answer_branches_reject_null_tools(action_name):
    capture = GROUNDED_ANSWER_ACTIONS[0]
    action = captured_action(capture)
    action["action"] = action_name
    action["tools"] = None
    assert not emitted_validator(capture["scope"]).is_valid(action)


@pytest.mark.parametrize("schema", [Action, ProposedAnswer])
@pytest.mark.parametrize("field", ["claim_id", "displayed_value", "evidence_ids", "fact_ids"])
def test_branch_constraints_preserve_admitted_references_and_complete_values(schema, field):
    capture = GROUNDED_ANSWER_ACTIONS[0]
    action = captured_action(capture)
    scope = deepcopy(capture["scope"])
    scope["candidates"] = [{"fact_id": "fact:admitted"}]
    action["answer"]["fact_ids"] = ["fact:admitted"]
    validator = emitted_validator(scope, schema)
    consumer = action if schema is Action else action["answer"]
    validator.validate(consumer)
    answer = action["answer"]
    if field == "claim_id":
        answer["claims"][0]["claim_id"] = "claim:invented"
    elif field == "displayed_value":
        answer["claims"][0]["displayed_value"] = {"losses": 32}
    else:
        answer[field] = ["invented"]
    assert not validator.is_valid(consumer)


def test_empty_scope_does_not_admit_claims_or_references():
    action = captured_action(GROUNDED_ANSWER_ACTIONS[0])
    validator = emitted_validator({"claims": [], "candidates": [], "evidence": []})
    assert not validator.is_valid(action)
    action["answer"]["claims"] = []
    action["answer"]["evidence_ids"] = []
    validator.validate(action)


@pytest.mark.parametrize(
    "tool_name",
    [
        "get_player_stats",
        "get_team_stats",
        "get_game_narrative",
        "compare_windows",
        "discover_facts",
        "search_archive",
        "get_evidence",
    ],
)
@pytest.mark.parametrize(
    "metric", [None, *dict.fromkeys((*PLAYER_METRICS, *TEAM_METRICS)), "invented_metric"]
)
def test_emitted_tool_metric_constraints_match_existing_runtime_validator(tool_name, metric):
    tool = {
        "name": tool_name,
        "question": "Captured prerequisite metric invariant",
        "metric": metric,
    }
    try:
        ToolCall.model_validate(tool)
    except ValidationError:
        runtime_accepts = False
    else:
        runtime_accepts = True
    action = {"action": "call_tools", "tools": [tool], "answer": None}
    validator = emitted_validator({"claims": [], "candidates": [], "evidence": []})
    assert validator.is_valid(action) is runtime_accepts
