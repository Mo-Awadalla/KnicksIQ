"""Requested scope authority via real socket HTTP, SQL and isolated Redis replay."""

import gzip
import json
import os

import pytest
from app.core.db import AsyncSessionLocal
from app.models.game import Game
from app.models.player import Player
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

BOUNDARY = {
    "name": "all_star_end",
    "date": "2026-02-15",
    "source_url": "https://www.nba.com/allstar/2026",
}
DENIAL = "The archive does not establish that these games were after the All-Star break."


class WindowAdapter(SyntheticAdapter):
    """Protocol stub; only backend claims may supply authoritative window metadata."""

    response_schema: dict | None = None

    def __init__(self, behavior="complete"):
        super().__init__({})
        self.behavior = behavior

    async def generate(self, *, system, user):
        payload = json.loads(user)
        claims = analyst_loop.payload_claims(payload)
        required = payload.get("required_claim_indexes", [])
        chosen = [claims[indices[0]] for indices in required] if required else claims
        chosen = list({c["claim_id"]: c for c in chosen}.values())
        has_boundary = bool(claims) and all(
            (c.get("window") or {}).get("requested", {}).get("calendar_boundary")
            == {**BOUNDARY, "relation": ">"}
            for c in claims
        )
        if payload["schema"]["title"] == "AnswerReview":
            proposal = analyst_loop.payload_proposed_answer(payload)
            declared_ids = [use["claim_id"] for use in proposal["claims"]]
            assertions = []
            for span in payload["review_spans"]:
                denies = DENIAL in span
                named = "After the All-Star break" in span
                unsupported = self.behavior in {"boundary-repair", "persistent-denial"} and (
                    (named and not has_boundary) or (denies and has_boundary)
                )
                assertions.append(
                    {
                        "text": span,
                        "assertion_type": "coverage"
                        if denies
                        else "factual"
                        if claims
                        else "conversational",
                        "verdict": "unsupported" if unsupported else "supported",
                        "offending_text": span.strip() if unsupported else None,
                        "supporting_claim_ids": declared_ids if not unsupported else [],
                        "supporting_evidence_ids": [],
                        "reason": (
                            "Named scope must agree with the complete immutable claim boundary."
                            if unsupported
                            else "The backend claims support this exact scripted statement."
                        ),
                    }
                )
            value = {"assertions": assertions, "follow_up_reviews": []}
        else:
            text = " ".join(c["statement"] for c in chosen) or "Please clarify the archive scope."
            if self.behavior in {"boundary-repair", "persistent-denial"} and chosen:
                values = {c["metric_id"]: c["value"] for c in chosen}
                if self.behavior == "persistent-denial" or payload.get("repair"):
                    text += " " + DENIAL
                else:
                    text = (
                        f"After the All-Star break, the Knicks had {values['wins']} wins and "
                        f"{values['losses']} losses across "
                        f"{chosen[0]['sample_size']} archived games."
                    )
            answer = {
                "text": text,
                "claims": [
                    {"claim_id": c["claim_id"], "displayed_value": c["value"]} for c in chosen
                ],
                "evidence_ids": [],
                "fact_ids": [],
                "follow_up_questions": [],
            }
            value = (
                answer
                if payload["schema"]["title"] == "ProposedAnswer"
                else {"action": "answer_from_available_evidence", "tools": [], "answer": answer}
            )
        raw = json.dumps(analyst_loop.encode_model_response(payload, value))
        assert self.response_schema is not None
        Draft202012Validator.check_schema(self.response_schema)
        Draft202012Validator(self.response_schema).validate(json.loads(raw))
        self.inputs.append(
            {
                "system": system,
                "user": payload,
                "schema": self.response_schema,
                "raw_response": raw,
                "schema_valid": True,
                "input_bytes": len((system + user).encode())
                + len(analyst_loop.encoded(self.response_schema).encode()),
            }
        )
        return raw


async def archive(monkeypatch, tmp_path):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    payload = json.loads(gzip.decompress(BUNDLE.read_bytes()))
    source = payload["data"]
    bundle, digest, adjustments = BUNDLE, SHA, []
    if not os.environ.get("KNICKSIQ_APPROVED_BUNDLE"):
        # Portable fixture has no road games. Preserve NYK/opponent scoring while
        # making three December wins meaningful away-game population members.
        candidates = [
            g
            for g in source["games"]
            if g["game_date"].startswith("2025-12")
            and g["home_team_id"] == "NYK"
            and g["home_score"] > g["away_score"]
        ][:3]
        assert len(candidates) == 3
        for game in candidates:
            game["home_team_id"], game["away_team_id"] = game["away_team_id"], game["home_team_id"]
            game["home_score"], game["away_score"] = game["away_score"], game["home_score"]
            adjustments.append(game["nba_game_id"])
            for event in source["events"]:
                if event["nba_game_id"] == game["nba_game_id"]:
                    event["home_score"], event["away_score"] = (
                        event["away_score"],
                        event["home_score"],
                    )
                    if event.get("score_margin") is not None:
                        event["score_margin"] = -event["score_margin"]
        bundle = tmp_path / "requested-window-synthetic.json.gz"
        digest = build_bundle(payload, bundle)
    async with AsyncSessionLocal() as db:
        release = await load_release_bundle(db, bundle, expected_sha256=digest, activate=True)
        games = list(
            (await db.execute(select(Game).where(Game.release_id == release.release_id))).scalars()
        )
        players = list((await db.execute(select(Player))).scalars())
    return (
        settings,
        source,
        {g.nba_game_id: g.id for g in games},
        {str(p.nba_player_id): p.id for p in players},
        digest,
        adjustments,
    )


def score(game):
    return (
        (game["home_score"], game["away_score"])
        if game["home_team_id"] == "NYK"
        else (game["away_score"], game["home_score"])
    )


def population(source, spec):
    games = sorted(source["games"], key=lambda g: (g["game_date"], g["nba_game_id"]))
    games = [g for g in games if "NYK" in {g["home_team_id"], g["away_team_id"]}]
    if spec.get("phase"):
        games = [g for g in games if g["season_type"] == spec["phase"]]
    if spec.get("start"):
        games = [g for g in games if g["game_date"] >= spec["start"]]
    if spec.get("end"):
        games = [g for g in games if g["game_date"] <= spec["end"]]
    if spec.get("away_wins"):
        games = [g for g in games if g["away_team_id"] == "NYK" and score(g)[0] > score(g)[1]]
    if spec.get("player"):
        person = next(p for p in source["players"] if p["full_name"] == spec["player"])
        observed = {
            s["nba_game_id"]
            for s in source["player_game_stats"]
            if s["nba_player_id"] == person["nba_player_id"] and s["minutes"] > 0
        }
        games = [g for g in games if g["nba_game_id"] in observed]
    if spec.get("count"):
        games = games[: spec["count"]] if spec["order"] == "first" else games[-spec["count"] :]
    return games


def expected_values(source, games, kind, player=None):
    if kind == "leader":
        ids = {g["nba_game_id"] for g in games}
        names = {p["nba_player_id"]: p["full_name"] for p in source["players"]}
        totals = {}
        for row in source["player_game_stats"]:
            if row["nba_game_id"] in ids and row["team_id"] == "NYK":
                name = names[row["nba_player_id"]]
                totals[name] = totals.get(name, 0) + row["points"]
        maximum = max(totals.values())
        return {
            "points:leaders": {
                "leaders": sorted(n for n, v in totals.items() if v == maximum),
                "total": maximum,
            }
        }
    if kind == "player":
        pid = next(p["nba_player_id"] for p in source["players"] if p["full_name"] == player)
        ids = {g["nba_game_id"] for g in games}
        rows = [
            s
            for s in source["player_game_stats"]
            if s["nba_game_id"] in ids and s["nba_player_id"] == pid and s["minutes"] > 0
        ]
        return {"points:average": sum(s["points"] for s in rows) / len(rows)}
    wins = sum(score(g)[0] > score(g)[1] for g in games)
    return (
        {"games:count": len(games)}
        if kind == "count"
        else {"wins": wins}
        if kind == "wins"
        else {"wins": wins, "losses": len(games) - wins}
    )


def requested(spec):
    value = {}
    for key in ("start", "end"):
        if spec.get(key):
            value["date_" + key] = spec[key]
    if spec.get("count"):
        value.update(
            relative_game_count=spec["count"],
            relative_game_order=spec["order"],
            relative_unit="appearances" if spec.get("player") else "games",
        )
    if spec.get("boundary"):
        value["calendar_boundary"] = {**BOUNDARY, "relation": spec["boundary"]}
    return value


def verify_protocol(receipt, adapter, settings):
    assert_committed_replay(receipt)
    assert receipt["real_provider_requests"] == 0
    assert settings.analyst_input_tokens == 8000 and settings.analyst_evidence_tokens == 6000
    assert settings.analyst_max_model_calls == 6 and settings.analyst_max_tool_rounds == 2
    assert all(entry["schema_valid"] and entry["input_bytes"] <= 8000 for entry in adapter.inputs)
    if adapter.inputs:
        assert any(e["user"]["schema"]["title"] == "AnswerReview" for e in adapter.inputs)


def verify_native_sources(receipt, source, game_ids, player_ids):
    state = receipt["capture"]["turn"].get("delivered_state", {})
    assert state == receipt["capture"]["turn"].get("committed_evidence_proposal", {})
    native = {c["claim_id"]: c for c in state.get("claims", [])}
    evidence = {e["evidence_id"]: e for e in state.get("evidence", [])}
    reverse_games = {v: k for k, v in game_ids.items()}
    reverse_players = {v: k for k, v in player_ids.items()}
    for citation in receipt["response"]["citations"]:
        if citation["type"] != "verified_claim":
            continue
        claim = citation["metadata"]["claim"]
        assert claim == native[claim["claim_id"]]
        refs = []
        for ref in claim["supporting_evidence_ids"]:
            assert ref in evidence
            refs.extend(
                evidence[ref]["metadata"]["source_evidence_ids"]
                if ref.startswith("calculation:")
                else [ref]
            )
        assert len(refs) == len(set(refs))
        prefix = claim["release_id"] + ":game:"
        expected = {prefix + str(g) for g in claim["game_ids"]}
        if claim["metric_id"].endswith(":leaders"):
            selected = {reverse_games[g] for g in claim["game_ids"]}
            expected = {
                prefix
                + str(game_ids[s["nba_game_id"]])
                + ":player:"
                + str(player_ids[str(s["nba_player_id"])])
                for s in source["player_game_stats"]
                if s["nba_game_id"] in selected and s["team_id"] == "NYK"
            }
        elif claim["subject_id"].startswith("player:"):
            pid = int(claim["subject_id"].split(":")[1])
            assert reverse_players[pid] in {str(p["nba_player_id"]) for p in source["players"]}
            expected = {ref + ":player:" + str(pid) for ref in expected}
        assert set(refs) == expected, "Complete native population references must not be truncated"
    for entry in receipt["model_inputs"]:
        for claim in analyst_loop.payload_claims(entry["user"]):
            assert claim == native[claim["claim_id"]]
        for item in analyst_loop.payload_evidence(entry["user"]):
            if item["evidence_id"] in evidence:
                assert item == evidence[item["evidence_id"]]
    return native


CASES = [
    (
        "frozen-date005",
        "What was their record after the All-Star break?",
        {"start": "2026-02-16", "boundary": ">"},
        "record",
        "boundary-repair",
    ),
    (
        "before-break",
        "What was the Knicks record before the All-Star break?",
        {"end": "2026-02-15", "boundary": "<="},
        "record",
        "complete",
    ),
    (
        "after-regular",
        "What was the Knicks regular season record after the All-Star break?",
        {"start": "2026-02-16", "boundary": ">", "phase": "regular"},
        "record",
        "complete",
    ),
    (
        "before-regular",
        "What was the Knicks regular season record before the All-Star break?",
        {"end": "2026-02-15", "boundary": "<=", "phase": "regular"},
        "record",
        "complete",
    ),
    (
        "after-playoffs",
        "What was the Knicks playoff record after the All-Star break?",
        {"start": "2026-02-16", "boundary": ">", "phase": "playoffs"},
        "record",
        "complete",
    ),
    (
        "before-playoffs",
        "What was the Knicks playoff record before the All-Star break?",
        {"end": "2026-02-15", "boundary": "<=", "phase": "playoffs"},
        "record",
        "complete",
    ),
    (
        "explicit-january",
        "How did the Knicks perform from January 1 through January 31?",
        {"start": "2026-01-01", "end": "2026-01-31"},
        "record",
        "complete",
    ),
    (
        "frozen-date009",
        "How many games did they play between March 1 and March 15?",
        {"start": "2026-03-01", "end": "2026-03-15"},
        "count",
        "complete",
    ),
    (
        "december-road-wins",
        "How many road games did they win in December?",
        {"start": "2025-12-01", "end": "2025-12-31", "away_wins": True},
        "wins",
        "complete",
    ),
    (
        "last-three-leader",
        "Who led the team in scoring over the last 3 games?",
        {"count": 3, "order": "last"},
        "leader",
        "complete",
    ),
    (
        "last-five-record",
        "What was the Knicks record in their last 5 games?",
        {"count": 5, "order": "last"},
        "record",
        "complete",
    ),
    (
        "first-ten-record",
        "What was their record in the first 10 games?",
        {"count": 10, "order": "first"},
        "record",
        "complete",
    ),
    (
        "last-regular",
        "What was their record over the final 15 regular-season games?",
        {"count": 15, "order": "last", "phase": "regular"},
        "record",
        "complete",
    ),
    (
        "player-last-five",
        "What was Brunson's scoring average over his last 5 games?",
        {"count": 5, "order": "last", "player": "Jalen Brunson"},
        "player",
        "complete",
    ),
    (
        "player-after-break",
        "What was Brunson's scoring average after the All-Star break?",
        {"start": "2026-02-16", "boundary": ">", "player": "Jalen Brunson"},
        "player",
        "complete",
    ),
    (
        "player-before-break",
        "What was Brunson's scoring average before the All-Star break?",
        {"end": "2026-02-15", "boundary": "<=", "player": "Jalen Brunson"},
        "player",
        "complete",
    ),
    (
        "persistent-scope-denial",
        "What was their record after the All-Star break?",
        {"start": "2026-02-16", "boundary": ">"},
        "record",
        "persistent-denial",
    ),
]


@pytest.mark.parametrize("name,question,spec,kind,behavior", CASES, ids=[c[0] for c in CASES])
async def test_requested_window_reaches_writer_reviewer_and_native_citations_socket_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,
    spec,
    kind,
    behavior,  # noqa: F811
):
    settings, source, game_ids, player_ids, digest, adjustments = await archive(
        monkeypatch, tmp_path
    )
    games = population(source, spec)
    adapter = WindowAdapter(behavior)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await record_exchange(client, local_redis, adapter, question, "window-" + name)
    expected = expected_values(source, games, kind, spec.get("player")) if games else {}
    receipt.update(
        archive_sha256=digest,
        synthetic_road_adjustments=adjustments,
        expected={
            "values": expected,
            "game_ids": [game_ids[g["nba_game_id"]] for g in games],
            "requested": requested(spec),
            "phase": spec.get("phase"),
        },
    )
    save_receipt(tmp_path, record_property, "window-" + name, receipt)
    verify_protocol(receipt, adapter, settings)
    native = verify_native_sources(receipt, source, game_ids, player_ids)
    claims = [
        c["metadata"]["claim"]
        for c in receipt["response"]["citations"]
        if c["type"] == "verified_claim"
    ]
    if not games:
        assert name == "before-playoffs" and os.environ.get("KNICKSIQ_APPROVED_BUNDLE")
        assert not claims
        assert all(not analyst_loop.payload_claims(e["user"]) for e in adapter.inputs)
        return
    assert set(c["metric_id"] for c in claims) == set(expected)
    committed_scope = receipt["capture"]["turn"]["delivered_state"]["scope"]
    for key in ("start", "end"):
        if spec.get(key):
            assert committed_scope["date_" + key] == spec[key]
    for claim in claims:
        value = expected[claim["metric_id"]]
        assert claim["value"] == (
            pytest.approx(value) if isinstance(value, (int, float)) else value
        )
        assert set(claim["game_ids"]) == {game_ids[g["nba_game_id"]] for g in games}
        assert claim["sample_size"] == len(games)
        if spec.get("phase"):
            assert claim["season_type"] == spec["phase"]
        if spec.get("away_wins"):
            assert claim["filters"]["home_away"] == "away"
            assert claim["filters"]["game_result"] == "W"
        if kind == "player":
            assert claim["denominator"] == len(games)
            assert claim["window"]["date_start"] == games[0]["game_date"]
            assert claim["window"]["date_end"] == games[-1]["game_date"]
        wanted = requested(spec)
        actual = (claim.get("window") or {}).get("requested", {})
        assert all(actual.get(k) == v for k, v in wanted.items()), (
            "Requested scope authority was lost"
        )
        assert all(v is not None for v in actual.values())
        assert native[claim["claim_id"]] == claim
    for entry in adapter.inputs:
        for claim in analyst_loop.payload_claims(entry["user"]):
            actual = (claim.get("window") or {}).get("requested", {})
            assert all(actual.get(k) == v for k, v in requested(spec).items())
    assert DENIAL not in receipt["response"]["answer"]
    assert receipt["response"]["llm_validated"] is (behavior != "persistent-denial")
    if behavior == "boundary-repair":
        assert len(adapter.inputs) == 2, (
            "Boundary authority must avoid the observed four-wire false denial"
        )
        assert receipt["response"]["answer"].startswith("After the All-Star break")
    if behavior == "persistent-denial":
        assert len(adapter.inputs) >= 2
    if os.environ.get("KNICKSIQ_APPROVED_BUNDLE") and name == "frozen-date005":
        assert expected == {"wins": 34, "losses": 12} and len(games) == 46


COMPARISONS = [
    ("month-groups", "Compare their January record with their February record."),
    ("first-last-groups", "Compare their first 10 games with their last 10 games."),
    ("all-star-player-comparison", "Compare Bridges' scoring before and after the All-Star break."),
    ("season-baseline", "Compare Brunson's last 5 games with his season average."),
]


@pytest.mark.parametrize("name,question", COMPARISONS, ids=[c[0] for c in COMPARISONS])
async def test_existing_grouped_and_baseline_windows_keep_their_own_populations_socket_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,  # noqa: F811
):
    settings, source, game_ids, player_ids, digest, adjustments = await archive(
        monkeypatch, tmp_path
    )
    adapter = WindowAdapter()
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await record_exchange(client, local_redis, adapter, question, "window-" + name)
    if name == "month-groups":
        specs = [
            ("January", {"start": "2026-01-01", "end": "2026-01-31"}),
            ("February", {"start": "2026-02-01", "end": "2026-02-28"}),
        ]
    elif name == "first-last-groups":
        specs = [
            ("First 10 games", {"count": 10, "order": "first"}),
            ("Last 10 games", {"count": 10, "order": "last"}),
        ]
    elif name == "season-baseline":
        specs = [
            ("current", {"player": "Jalen Brunson", "count": 5, "order": "last"}),
            ("baseline", {"player": "Jalen Brunson"}),
        ]
    else:
        specs = [
            ("before", {"player": "Mikal Bridges", "end": "2026-02-15"}),
            ("after", {"player": "Mikal Bridges", "start": "2026-02-16"}),
        ]
    populations = {label: population(source, spec) for label, spec in specs}
    assert all(populations.values())
    receipt.update(
        archive_sha256=digest,
        synthetic_road_adjustments=adjustments,
        expected={
            label: {
                "game_ids": [game_ids[g["nba_game_id"]] for g in games],
                "observed_start": games[0]["game_date"],
                "observed_end": games[-1]["game_date"],
            }
            for label, games in populations.items()
        },
    )
    save_receipt(tmp_path, record_property, "window-" + name, receipt)
    verify_protocol(receipt, adapter, settings)
    native = verify_native_sources(receipt, source, game_ids, player_ids)
    assert receipt["response"]["llm_validated"] is True
    claims = [
        c["metadata"]["claim"]
        for c in receipt["response"]["citations"]
        if c["type"] == "verified_claim"
    ]
    if name in {"month-groups", "first-last-groups"}:
        assert len(claims) == 2
        for label, spec in specs:
            claim = next(c for c in claims if c["window"].get("comparison_group") == label)
            games = populations[label]
            assert claim["value"] == {
                "games": len(games),
                **expected_values(source, games, "record"),
            }
            assert set(claim["game_ids"]) == {game_ids[g["nba_game_id"]] for g in games}
            assert claim["sample_size"] == claim["denominator"] == len(games)
            assert claim["window"]["date_start"] == games[0]["game_date"]
            assert claim["window"]["date_end"] == games[-1]["game_date"]
            scoped = claim["window"].get("requested")
            if scoped:
                assert all(scoped.get(k) == v for k, v in requested(spec).items())
    elif name == "season-baseline":
        assert len(claims) == 2
        for label, spec in specs:
            games = populations[label]
            claim = next(
                c
                for c in claims
                if set(c["game_ids"]) == {game_ids[g["nba_game_id"]] for g in games}
            )
            assert claim["value"] == pytest.approx(
                expected_values(source, games, "player", "Jalen Brunson")["points:average"]
            )
            assert claim["sample_size"] == claim["denominator"] == len(games)
            assert claim["window"]["date_start"] == games[0]["game_date"]
            assert claim["window"]["date_end"] == games[-1]["game_date"]
            scoped = claim["window"].get("requested", {})
            if label == "current":
                assert all(scoped.get(k) == v for k, v in requested(spec).items())
            else:
                assert not scoped.get("relative_game_count")
                assert not scoped.get("date_start") and not scoped.get("date_end")
    else:
        claim = next(c for c in claims if c["metric_id"] == "points:window_comparison")
        before = expected_values(source, populations["before"], "player", "Mikal Bridges")[
            "points:average"
        ]
        after = expected_values(source, populations["after"], "player", "Mikal Bridges")[
            "points:average"
        ]
        assert claim["value"] == pytest.approx(
            {"before": before, "after": after, "delta": after - before}
        )
        assert claim["window"]["boundary"] == "2026-02-15"
        assert claim["window"]["source_url"] == BOUNDARY["source_url"]
        assert len(claim["baseline_claim_ids"]) == 2
        assert not claim["window"].get("requested", {}).get("calendar_boundary"), (
            "Two-sided comparison must not receive a single-sided parent boundary"
        )
        for label, _ in specs:
            games = populations[label]
            window = claim["window"][label]
            assert set(window["game_ids"]) == {game_ids[g["nba_game_id"]] for g in games}
            assert window["sample_size"] == len(games)
            assert window["dates"]["date_start"] == games[0]["game_date"]
            assert window["dates"]["date_end"] == games[-1]["game_date"]
            baseline = next(
                native[ref]
                for ref in claim["baseline_claim_ids"]
                if set(native[ref]["game_ids"]) == set(window["game_ids"])
            )
            assert baseline["value"] == pytest.approx(before if label == "before" else after)
            assert baseline["denominator"] == len(games)


GUARDS = [
    ("unavailable-season", "What was the Knicks record after the All-Star break in 2024-25?"),
    ("future-season", "What was the Knicks record after the All-Star break in 2026-27?"),
    ("invalid-date", "What was their record from February 30 through March 2?"),
    (
        "conflicting-after",
        "What was the Knicks record after the All-Star break from January 1 through January 31?",
    ),
    (
        "conflicting-before",
        "What was the Knicks record before the All-Star break from March 1 through March 15?",
    ),
    ("undefined-back-to-back", "How many back-to-backs did they win in February?"),
    ("unsupported-period", "What was the Knicks record in the first quarter?"),
    ("future-empty", "What was the Knicks record from 2099-01-01 through 2099-01-15?"),
]


@pytest.mark.parametrize("name,question", GUARDS, ids=[c[0] for c in GUARDS])
async def test_unsupported_or_conflicting_windows_do_not_gain_factual_authority_socket_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,  # noqa: F811
):
    settings, source, game_ids, player_ids, digest, adjustments = await archive(
        monkeypatch, tmp_path
    )
    adapter = WindowAdapter()
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await record_exchange(client, local_redis, adapter, question, "window-" + name)
    receipt.update(
        archive_sha256=digest,
        synthetic_road_adjustments=adjustments,
        expected={"factual_claims": []},
    )
    save_receipt(tmp_path, record_property, "window-" + name, receipt)
    verify_protocol(receipt, adapter, settings)
    verify_native_sources(receipt, source, game_ids, player_ids)
    assert not any(c["type"] == "verified_claim" for c in receipt["response"]["citations"])
    assert all(not analyst_loop.payload_claims(e["user"]) for e in adapter.inputs)
    assert not receipt["capture"]["turn"].get("delivered_state", {}).get("claims")
