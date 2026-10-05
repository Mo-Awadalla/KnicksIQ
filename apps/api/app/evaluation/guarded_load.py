"""Private counted ORIGINAL warm-load gate, never a release/launch approval.

Run only after the original disabled120 score and distinct full primary/shadow
quality stages pass in the same admitted aggregate goal. The unchanged stress.py
performs real socket HTTP readiness, warmup, 61-second cooldown, ten archive readers
for 30 seconds and ten distinct analyst questions. Ordinary quotas remain enabled.
Shadow0.1 membership is fixed before execution; only selected requests may transmit.

The added load ceiling is 66: original warmup1 + analyst10, times the unchanged
six-model-call ceiling. Existing smoke/primary/shadow and aggregate dollar caps
are untouched. No new journal, replay, retry or resume after uncertainty exists.
HTTP mutations, phase conflicts, admission denial, missing normal reservations,
foreign joins and uncertain provider transmissions stop the SAME admitted goal.
Synthetic socket regressions do not establish the paid load or release gate.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import os
import socket
import sqlite3
import sys
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import httpx
import uvicorn

from app.core.config import get_settings
from app.evaluation.guarded_release import (
    APPROVAL,
    DESIGNATED_KEY_SHA256,
    FROZEN,
    GOLD,
    SOURCES,
    VERSION,
    Admission,
    GuardedSession,
    durable_json,
    goal_context,
    require,
    validate_counted_receipt_joins,
)
from app.evaluation.release_runner import SCORING_VERSION, digest, file_hash, load_contract
from app.evaluation.trace_capture import capture_turn
from app.evaluation.verification_budget import SPENDING_DIRECTION_SHA256, VerificationBudget
from app.services.release_evidence import MINIMUMS, evaluation_request_id, validate_shadow_stage

STRESS = Path(__file__).resolve().parents[4] / "tools/release/stress.py"
STRESS_SHA256 = "6e2d13d3015ad60a8af561cb43528a932bb24ec17de67c6d34623fb916e13371"
LOAD_REQUEST_CAP = 66


def load_cases(*, distinct_questions: bool = True) -> list[dict]:
    """Read original literals from the pinned stress source, not a second workload."""
    require(file_hash(STRESS) == STRESS_SHA256, "Original stress workload changed")
    function = next(
        node
        for node in ast.parse(STRESS.read_text()).body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
    )
    assignment = next(
        node
        for node in function.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "question" for target in node.targets)
    )
    warmup = ast.literal_eval(assignment.value)
    branch = next(
        node
        for node in function.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Attribute)
        and node.test.attr == "distinct_questions"
    )
    original = ast.literal_eval(branch.body[0].value.generators[0].iter)
    require(
        len(original) == 10 and len(set(original)) == 10 and warmup["season"] == "2025-26",
        "Original analyst workload is not warmup plus ten distinct requests",
    )
    questions = original if distinct_questions else [warmup["question"]] * 10
    return [{"id": "load-warmup", "question": warmup["question"], "context": []}] + [
        {"id": f"load-analyst-{index:02d}", "question": question, "context": []}
        for index, question in enumerate(questions, 1)
    ]


def load_identity() -> dict:
    from app.api.analysis import _sample_shadow

    cases = load_cases()
    request_ids = [evaluation_request_id(STRESS_SHA256, "shadow", case["id"]) for case in cases]
    return {
        "mode": "shadow",
        "stage": "load",
        "stress_sha256": STRESS_SHA256,
        "cases": cases,
        "request_ids": request_ids,
        "shadow_membership": [_sample_shadow(identity, 0.1) for identity in request_ids],
        "duration_seconds": 30,
        "cooldown_seconds": 61,
        "archive_readers": 10,
        "analyst_requests": 10,
        "warmup_requests": 1,
        "request_cap": LOAD_REQUEST_CAP,
        "archive_p95_ms_exclusive": 1000,
        "analyst_p95_ms_exclusive": 4000,
        "original_stress_requires_zero_errors": True,
    }


class LoadAdmission(Admission):
    def verify_inputs(self) -> None:
        super().verify_inputs()
        for field, path in {
            "guarded_cli_sha256": Path(__file__).with_name("guarded_release.py"),
            "runner_sha256": Path(__file__).with_name("release_runner.py"),
            "load_harness_sha256": Path(__file__),
            "load_stress_sha256": STRESS,
            "verification_budget_sha256": Path(__file__).with_name("verification_budget.py"),
            "verification_adapter_sha256": Path(__file__).with_name("verification_adapter.py"),
        }.items():
            require(
                file_hash(path) == self.load_binding[field],
                "Admitted load/accounting source changed: " + field,
            )

    async def verify_environment(self, identity: dict) -> None:
        from app.api.analysis import _sample_shadow

        require(identity == load_identity(), "Changed original load/sampler identity")
        # Reuse all original source, settings, Docker, candidate, ledger and fresh
        # provider checks. Original gold remains frozen, not a replacement gold.
        original_ids = [
            evaluation_request_id(self.contract_sha256, "shadow", case["id"]) for case in self.cases
        ]
        await super().verify_environment(
            {
                "mode": "shadow",
                "expectations_sha256": self.contract_sha256,
                "request_ids": original_ids,
                "shadow_membership": [_sample_shadow(value, 0.1) for value in original_ids],
            }
        )
        durable_json(
            self.artifact_dir / "load-environment-admission.json",
            {
                "identity": identity,
                "resources": self.resource_binding,
                "status": "admitted_no_completion",
            },
        )


class LoadHTTP:
    """Bind unchanged stress HTTP bodies to exact counted turn identities once."""

    def __init__(self, app, session, cases, request_ids):
        require(
            len(cases) == len(request_ids) == 11,
            "Original load requires eleven analyst HTTP requests",
        )
        self.app, self.session = app, session
        self.cases, self.request_ids = cases, request_ids
        self.used: set[int] = set()
        self.observations: dict[str, dict] = {}

    async def deny(self, send, status, error):
        body = json.dumps({"error": {"code": error}}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        try:
            self.session.execution.check()
        except ValueError:
            return await self.deny(send, 503, "counted_load_stopped")
        if scope["path"] != "/analysis/query":
            return await self.app(scope, receive, send)
        try:
            chunks = []
            while True:
                message = await receive()
                require(message["type"] == "http.request", "Interrupted load request")
                chunks.append(message.get("body", b""))
                require(sum(map(len, chunks)) <= 4096, "Changed original load body bound")
                if not message.get("more_body"):
                    break
            body = json.loads(b"".join(chunks))
            require(
                scope["method"] == "POST"
                and isinstance(body, dict)
                and set(body) == {"question", "season"}
                and body["season"] == "2025-26",
                "Changed original raw load HTTP payload",
            )
            candidates = [
                index
                for index, case in enumerate(self.cases)
                if index not in self.used and body["question"] == case["question"]
            ]
            require(len(candidates) == 1, "Changed or repeated original load question")
            index = candidates[0]
            self.used.add(index)  # No await: claim the HTTP identity atomically.
            request_id = self.request_ids[index]
            body.update(turn_id=request_id, expected_revision=0)
            raw = json.dumps(body).encode()
            scope = dict(scope)
            scope["headers"] = [
                (key, value)
                for key, value in scope["headers"]
                if key.lower() not in {b"x-request-id", b"content-length"}
            ] + [
                (b"x-request-id", request_id.encode()),
                (b"content-length", str(len(raw)).encode()),
            ]
        except (ValueError, KeyError, TypeError) as exc:
            self.session.failed(type(exc).__name__)
            return await self.deny(send, 409, "original_load_binding_denied")
        consumed = False
        status, response_chunks = None, []
        response_messages = []
        started = time.perf_counter()

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return await receive()

        async def observe(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                response_chunks.append(message.get("body", b""))
            response_messages.append(message)

        observation = {
            "case_id": self.cases[index]["id"],
            "request_id": request_id,
            "original_payload": {"question": body["question"], "season": body["season"]},
            "bound_payload_sha256": digest(body),
            "stage": "load",
            "mode": "shadow",
        }
        try:
            with capture_turn() as capture:
                await self.app(scope, replay, observe)
                observation["capture"] = capture
            self.session.execution.check()
            response = json.loads(b"".join(response_chunks))
            require(
                status == 200
                and response.get("answer")
                and not response.get("refused")
                and response.get("citations")
                and response.get("request_id") == request_id,
                "Original load HTTP response is not factual/bound",
            )
            observation.update(status="complete", response=response)
            # Do not expose success before accounting and factual validation finish.
            for message in response_messages:
                await send(message)
        except BaseException as exc:
            observation.update(status="failed", error_type=type(exc).__name__)
            self.session.failed(type(exc).__name__)
            raise
        finally:
            observation.update(
                http_status=status, elapsed_ms=(time.perf_counter() - started) * 1000
            )
            self.observations[request_id] = observation
            durable_json(self.session.run_dir / f"http-{index:02d}.json", observation)


@asynccontextmanager
async def private_server(app, *, lifespan="on", port=0):
    """One real loopback-only Uvicorn server; no public/proxy client identity spoof."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(128)
    sock.setblocking(False)
    actual_port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=actual_port,
            lifespan=lifespan,
            log_level="warning",
            access_log=False,
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(30):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Private HTTP server exited before readiness")
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{actual_port}"
    finally:
        server.should_exit = True
        try:
            await task
        finally:
            sock.close()


def disabled_pass(root: Path, score_path: Path, observations_path: Path) -> dict:
    for path in (score_path, observations_path):
        require(
            path.resolve().is_relative_to(root),
            "Disabled evidence must remain in private evidence root",
        )
    score, observations = (
        json.loads(score_path.read_text()),
        json.loads(observations_path.read_text()),
    )
    metrics = score.get("metrics", {})
    require(
        score.get("status") == "scored"
        and score.get("mode") == "disabled"
        and metrics.get("query_count") == 120
        and metrics.get("semantic_case_count") == 50
        and metrics.get("missing_labels") == 0
        and metrics.get("exact_numeric_correctness") == 1
        and metrics.get("canonical_entity_correctness") == 1
        and metrics.get("correct_abstention_rate") == 1
        and metrics.get("citation_correctness", 0) >= 0.95
        and metrics.get("paraphrase_success", 0) >= 0.95,
        "Original disabled120 acceptance must pass before counted load",
    )
    inputs = score.get("inputs", {})
    require(
        inputs.get("contract") == FROZEN[GOLD]
        and inputs.get("approval") == FROZEN[APPROVAL]
        and inputs.get("observations") == file_hash(observations_path)
        and score.get("runner_sha256") == file_hash(Path(__file__).with_name("release_runner.py"))
        and observations.get("status") == "captured_pending_semantic_review"
        and observations.get("mode") == "disabled"
        and observations.get("paid_requests") == 0
        and observations.get("expectations_sha256") == FROZEN[GOLD]
        and observations.get("approval_sha256") == FROZEN[APPROVAL]
        and len(observations.get("observations", [])) == 120,
        "Disabled score/source/120-observation identity mismatch",
    )
    return {
        "score_sha256": file_hash(score_path),
        "observations_sha256": file_hash(observations_path),
    }


def original_quality_pass(
    root: Path,
    goal: Path,
    budget: VerificationBudget,
    primary_score: Path,
    shadow_score: Path,
    shadow_record: Path,
) -> dict:
    """Admit load from reviewed original quality, never transport completion alone."""
    error = "Completed successful original primary and shadow quality stages are required"
    try:
        with budget._connect() as db:
            phases = dict(db.execute("SELECT mode, status FROM guard_runs"))
            stored = json.loads(db.execute("SELECT binding FROM guard_goal").fetchone()[0])
        require(phases.get("primary") == phases.get("shadow") == "complete", error)
        contract = load_contract(root / GOLD, root / APPROVAL)
        snapshots = {}
        hashes = {}
        for mode, score_path in (("primary", primary_score), ("shadow", shadow_score)):
            score_path = score_path.resolve()
            require(score_path.is_relative_to(root), error)
            observation_path = goal / mode / "observations.json"
            summary_path = goal / mode / "execution-summary.json"
            score = json.loads(score_path.read_text())
            observed = json.loads(observation_path.read_text())
            summary = json.loads(summary_path.read_text())
            metrics = score.get("metrics", {})
            require(
                score.get("status") == "scored"
                and score.get("mode") == mode
                and score.get("scoring_version") == SCORING_VERSION
                and metrics.get("query_count") == 120
                and metrics.get("semantic_case_count") == 50
                and metrics.get("missing_labels") == 0
                and metrics.get("missing_ranked_traces") == 0
                and all(
                    type(metrics.get(name)) in (int, float) and minimum <= metrics[name] <= 1
                    for name, minimum in MINIMUMS.items()
                ),
                error,
            )
            inputs = score.get("inputs", {})
            configuration = observed.get("configuration", {})
            require(
                inputs.get("contract") == FROZEN[GOLD]
                and inputs.get("approval") == FROZEN[APPROVAL]
                and inputs.get("observations") == file_hash(observation_path)
                and score.get("runner_sha256") == stored["runner_sha256"]
                and observed.get("runner_sha256") == stored["runner_sha256"]
                and observed.get("status") == "captured_pending_semantic_review"
                and observed.get("mode") == mode
                and observed.get("expectations_sha256") == FROZEN[GOLD]
                and observed.get("approval_sha256") == FROZEN[APPROVAL]
                and configuration.get("analysis_answer_mode")
                == ("llm_primary" if mode == "primary" else "shadow")
                and configuration.get("analysis_shadow_sample_rate") == 0.1
                and configuration.get("analyst_evidence_loop_enabled") is True
                and summary.get("status") == "complete"
                and summary.get("mode") == mode,
                error,
            )
            expected_ids = [
                evaluation_request_id(FROZEN[GOLD], mode, case["id"]) for case in contract["cases"]
            ]
            observations = observed.get("observations", [])
            require(
                observed.get("request_ids") == expected_ids
                and [row["case_id"] for row in observations]
                == [case["id"] for case in contract["cases"]]
                and [row["request_id"] for row in observations] == expected_ids,
                error,
            )
            snapshots[mode] = (observed, summary)
            hashes[mode] = {
                "score_sha256": file_hash(score_path),
                "observations_sha256": file_hash(observation_path),
                "execution_summary_sha256": file_hash(summary_path),
            }
        with budget._connect() as db:
            receipts = [
                json.loads(row[0])
                for row in db.execute("SELECT receipt FROM guard_receipts ORDER BY ticket")
            ]
            binding = db.execute("SELECT binding FROM identity").fetchone()[0]
            normal = {}
            for (raw,) in db.execute("SELECT receipt FROM guard_normal"):
                reservation = json.loads(raw)
                normal[reservation["identity"]] = reservation
        validate_counted_receipt_joins(budget, binding, receipts)
        accounting = budget.snapshot()
        for mode, (observed, summary) in snapshots.items():
            stage_receipts = [row for row in receipts if row["stage"] == mode]
            require(
                stage_receipts
                and observed.get("paid_requests") == len(stage_receipts)
                and accounting["stages"][mode]["requests"]
                - accounting["stages"][mode].get("inherited_requests", 0)
                == len(stage_receipts)
                and summary["accounting"]["stages"][mode]["requests"]
                - summary["accounting"]["stages"][mode].get("inherited_requests", 0)
                == len(stage_receipts)
                and [row for row in summary["calls"] if row["stage"] == mode] == stage_receipts,
                error,
            )
            counts = {}
            for row in stage_receipts:
                reservation = normal.get(row["normal_reservation_id"])
                require(
                    reservation is not None
                    and reservation["settled"]
                    and not reservation["uncertain"]
                    and reservation["request_id"] == row["request_id"]
                    and row["journal_ticket"] in reservation["tickets"],
                    error,
                )
                require(
                    row["request_id"] == evaluation_request_id(FROZEN[GOLD], mode, row["case_id"]),
                    error,
                )
                counts[row["request_id"]] = counts.get(row["request_id"], 0) + 1
            require(set(counts) <= set(observed["request_ids"]), error)
            for case, observation in zip(contract["cases"], observed["observations"], strict=True):
                turn, response = observation["capture"]["turn"], observation["response"]
                count = counts.get(observation["request_id"], 0)
                require(
                    observation.get("http_status") == 200
                    and turn.get("request_id")
                    == response.get("request_id")
                    == observation["request_id"]
                    and turn.get("model_calls") == count
                    and type(turn.get("model_calls")) is int
                    and 0 <= count <= 6
                    and turn.get("answer_mode")
                    == ("llm_primary" if mode == "primary" else "shadow")
                    and turn.get("release") == response.get("data_version") == VERSION
                    and turn.get("state_committed") is response.get("state_committed") is True
                    and turn.get("replayed") is False
                    and turn.get("error") is None
                    and response.get("refused") is (case["disposition"] == "refuse"),
                    error,
                )
                if mode == "primary":
                    answer = case["disposition"] == "answer"
                    require(
                        turn.get("model_validated") is answer
                        and response.get("llm_validated") is answer
                        and (count > 0 if answer else count == 0)
                        and turn.get("delivered_mode")
                        == (
                            "llm_analyst"
                            if answer
                            else "clarification"
                            if case["disposition"] == "clarify"
                            else None
                        ),
                        error,
                    )
        shadow_record = shadow_record.resolve()
        require(shadow_record.is_relative_to(root), error)
        record = json.loads(shadow_record.read_text())
        item = record["checks"]["shadow_evaluation"]
        stage_path = (root / item["path"]).resolve()
        require(
            stage_path.is_relative_to(root)
            and record.get("tested_commit")
            and item.get("status") == "passed"
            and item.get("tested_commit") == record["tested_commit"]
            and record["hashes"]["bundle"] == SOURCES["bundle"][1]
            and record["hashes"]["evaluation"] == FROZEN[GOLD]
            and (root / record["evaluation_contract"]["path"]).resolve() == root / GOLD
            and (root / record["approvals"]["evaluation_labels"]["path"]).resolve()
            == root / APPROVAL
            and record["pre_promotion_configuration"].get("answer_mode") == "shadow"
            and record["pre_promotion_configuration"].get("shadow_sample_rate") == 0.1
            and record["pre_promotion_configuration"].get("analyst_evidence_loop_enabled") is True
            and not validate_shadow_stage(record, root),
            error,
        )
        stage = json.loads(stage_path.read_text())
        observed = snapshots["shadow"][0]
        require(
            observed.get("shadow_membership") == [turn["sampled"] for turn in stage["turns"]]
            and observed.get("shadow_selected_count") == sum(observed["shadow_membership"]),
            error,
        )
        fields = (
            "request_id",
            "sampled",
            "model_calls",
            "model_validated",
            "delivered_mode",
            "state_committed",
            "replayed",
            "error",
        )
        for staged, observation in zip(stage["turns"], observed["observations"], strict=True):
            captured = observation["capture"]["turn"]
            require(
                staged["case_id"] == observation["case_id"]
                and all(staged.get(field) == captured.get(field) for field in fields)
                and staged["refused"] is observation["response"]["refused"]
                and observation["response"].get("llm_validated") is False,
                error,
            )
        hashes["shadow_record_sha256"] = file_hash(shadow_record)
        hashes["shadow_stage_sha256"] = file_hash(stage_path)
        return hashes
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        raise ValueError(error) from exc


async def run(args) -> None:
    from app.api import analysis
    from app.services import analyst_loop

    root, goal = args.evidence_root.resolve(), args.goal_dir.resolve()
    require(
        goal.is_relative_to(root) and goal != root,
        "Load artifacts must remain in private evidence root",
    )
    identity = load_identity()
    for relative, expected in FROZEN.items():
        require(
            file_hash(root / relative) == expected, "Frozen original input changed: " + relative
        )
    prerequisite = disabled_pass(
        root, args.disabled_score.resolve(), args.disabled_observations.resolve()
    )
    key = get_settings().openrouter_api_key
    require(
        isinstance(key, str) and hashlib.sha256(key.encode()).hexdigest() == DESIGNATED_KEY_SHA256,
        "Missing owner-designated provider key",
    )
    ledger, binding, anchor_path = goal_context(root, goal, args)
    binding_sha = digest(binding)
    anchor = json.loads(anchor_path.read_text())
    require(
        anchor["goal_dir"] == str(goal) and anchor["binding_sha256"] == binding_sha,
        "Load does not use the SAME original admitted aggregate goal",
    )
    budget = VerificationBudget(goal / "goal.sqlite", binding=binding_sha)
    require(
        budget.snapshot()["inherited_calls"] == binding.get("successor", {}).get("calls", []),
        "Successor inherited request inventory differs before load",
    )
    original_cases = load_contract(root / GOLD, root / APPROVAL)["cases"]
    shadow_cap = 6 * sum(
        analysis._sample_shadow(evaluation_request_id(FROZEN[GOLD], "shadow", case["id"]), 0.1)
        for case in original_cases
    )
    require(
        not budget.snapshot()["stopped"]
        and budget.snapshot()["spending_direction_sha256"] == SPENDING_DIRECTION_SHA256
        and budget.request_cap("load") == LOAD_REQUEST_CAP
        and budget.request_cap("primary") == 720
        and budget.request_cap("smoke") == 9
        and budget.request_cap("shadow") == shadow_cap,
        "Stopped/unapproved goal or changed original phase ceilings",
    )
    quality_prerequisite = original_quality_pass(
        root, goal, budget, args.primary_score, args.shadow_score, args.shadow_record
    )
    with budget._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        stored = json.loads(db.execute("SELECT binding FROM guard_goal").fetchone()[0])
        for field in binding:
            if field != "historical_floor_nusd":
                require(
                    stored[field] == json.loads(json.dumps(binding[field])),
                    "Original aggregate binding changed",
                )
        require(
            not db.execute("SELECT 1 FROM guard_runs WHERE status != 'complete'").fetchone(),
            "Interrupted/failed/active original phase cannot resume or overlap",
        )
        db.execute("INSERT INTO guard_runs VALUES ('load', 'started')")
    ledger.run_id = stored["redis_run_id"]
    ledger.floor = Decimal(stored["historical_floor_nusd"]) / 1_000_000_000
    run_dir = goal / "load"
    admission = LoadAdmission(evidence_root=root, artifact_dir=run_dir, api_key=key, ledger=ledger)
    admission.resource_binding = stored["resources"]
    admission.alias_binding = stored["resources"]["qdrant_aliases"]
    admission.load_binding = stored
    session = GuardedSession(
        admission=admission,
        budget=budget,
        ledger=ledger,
        api_key=key,
        mode="shadow",
        stage="load",
        cases=identity["cases"],
        request_ids=identity["request_ids"],
        run_dir=run_dir,
    )
    status, process = "failed", None
    original_adapter, original_legacy = analyst_loop.get_llm_adapter, analysis.get_llm_adapter
    wrapper = None
    initial_tickets = {call["id"] for call in budget.snapshot()["calls"]}
    command = None
    try:
        await session.execution.verify_environment(identity)
        require(
            any(identity["shadow_membership"]),
            "Original fixed load has no counted shadow transmission",
        )
        durable_json(
            run_dir / "workload-binding.json",
            {
                "identity": identity,
                "disabled_pass": prerequisite,
                "original_quality_pass": quality_prerequisite,
                "aggregate_binding_sha256": binding_sha,
                "harness_sha256": file_hash(Path(__file__)),
                "stage_cap_derivation": "(warmup1 + original analyst10) * unchanged calls6 = 66",
            },
        )
        with session.installed():
            analyst_loop.get_llm_adapter = lambda **_kwargs: session.execution.adapter("load", None)

            def denied(**_kwargs):
                session.failed("uncounted_legacy_load_adapter")
                raise RuntimeError("Uncounted load provider path denied")

            analysis.get_llm_adapter = denied
            from app.main import create_app

            wrapper = LoadHTTP(create_app(), session, identity["cases"], identity["request_ids"])
            async with private_server(wrapper, port=args.port) as base_url:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    trust_env=False,
                    follow_redirects=False,
                    headers={"X-Forwarded-Proto": "https"},
                ) as client:
                    ready, archive = (
                        await client.get("/health/ready"),
                        await client.get("/archive/status"),
                    )
                    require(
                        ready.status_code == 200
                        and ready.json().get("status") == "ready"
                        and ready.json().get("data_version") == VERSION
                        and archive.status_code == 200
                        and archive.json().get("data_version") == VERSION,
                        "Actual private API URL readiness/archive identity failed",
                    )
                    durable_json(
                        run_dir / "http-readiness.json",
                        {
                            "base_url": base_url,
                            "readiness": ready.json(),
                            "archive": archive.json(),
                        },
                    )
                command = [
                    sys.executable,
                    str(STRESS),
                    "--base-url",
                    base_url,
                    "--data-version",
                    VERSION,
                    "--duration",
                    "30",
                    "--output",
                    str(run_dir / "stress.json"),
                    "--local-https-proxy",
                    "--distinct-questions",
                ]
                durable_json(
                    run_dir / "stress-command.json",
                    {"argv": command, "stress_sha256": STRESS_SHA256},
                )
                with (
                    (run_dir / "stress.stdout.log").open("xb") as stdout,
                    (run_dir / "stress.stderr.log").open("xb") as stderr,
                ):
                    process = await asyncio.create_subprocess_exec(
                        *command, stdout=stdout, stderr=stderr
                    )
                    async with asyncio.timeout(240):
                        while process.returncode is None:
                            session.execution.check()
                            try:
                                await asyncio.wait_for(process.wait(), timeout=0.1)
                            except TimeoutError:
                                continue
                    require(
                        process.returncode == 0, "Original stress HTTP latency/error gate failed"
                    )
                session.execution.check()
                metrics = json.loads((run_dir / "stress.json").read_text())
                require(
                    metrics.get("passed") is True
                    and metrics["metrics"]["concurrency"] == 10
                    and metrics["metrics"]["analyst_requests"] == 10
                    and metrics["metrics"]["archive_p95_ms"] < 1000
                    and metrics["metrics"]["analyst_p95_ms"] < 4000
                    and not metrics["errors"],
                    "Original p95/error acceptance was not satisfied",
                )
        require(
            wrapper.used == set(range(11))
            and len(wrapper.observations) == 11
            and all(row["status"] == "complete" for row in wrapper.observations.values()),
            "Original eleven HTTP requests were not independently captured",
        )
        admission.verify_inputs()
        await ledger.read()
        session.validate_receipt_joins()
        receipts = {row["journal_ticket"]: row for row in session.receipts()}
        calls = [row for row in budget.snapshot()["calls"] if row["id"] not in initial_tickets]
        joined_ids = set()
        for call in calls:
            row = receipts.get(call["id"])
            require(
                row is not None
                and row["status"] == call["status"] == "settled"
                and row["cost_nusd"] == call["amount_nusd"]
                and row["stage"] == call["stage"] == "load"
                and row["mode"] == "shadow"
                and row["journal_binding"] == binding_sha
                and row["request_id"] in identity["request_ids"],
                "Missing exact load/provider/journal join",
            )
            joined_ids.add(row["request_id"])
        selected_ids = {
            value
            for value, selected in zip(
                identity["request_ids"], identity["shadow_membership"], strict=True
            )
            if selected
        }
        require(
            joined_ids == selected_ids
            and len(calls) <= LOAD_REQUEST_CAP
            and len(receipts) == len(budget.snapshot()["calls"]),
            "Selected load did not transmit, unselected load transmitted, or foreign receipt",
        )
        for request_id, selected in zip(
            identity["request_ids"], identity["shadow_membership"], strict=True
        ):
            observation = wrapper.observations[request_id]
            turn = observation["capture"]["turn"]
            count = sum(receipts[call["id"]]["request_id"] == request_id for call in calls)
            require(
                observation["response"].get("data_version") == VERSION
                and turn.get("request_id") == request_id
                and turn.get("answer_mode") == "shadow"
                and turn.get("sampled") is selected
                and turn.get("model_calls") == count
                and count <= 6
                and (selected or count == 0),
                "HTTP/sampler/actual model-call journal join differs",
            )
        with budget._connect() as db:
            normal = [json.loads(row[0]) for row in db.execute("SELECT receipt FROM guard_normal")]
        for receipt in receipts.values():
            reservation = next(
                (row for row in normal if row["identity"] == receipt["normal_reservation_id"]), None
            )
            require(
                reservation is not None
                and reservation["settled"]
                and not reservation["uncertain"]
                and reservation["request_id"] == receipt["request_id"]
                and receipt["journal_ticket"] in reservation["tickets"],
                "Missing settled normal reservation join",
            )
        status = "complete"
        print(
            json.dumps(
                {
                    "status": "original_counted_load_passed",
                    "paid_requests": len(calls),
                    "historical_provider_calls": 22,
                    "release_approved": False,
                }
            )
        )
    except BaseException as exc:
        session.failed(type(exc).__name__)
        raise
    finally:
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()
        analyst_loop.get_llm_adapter, analysis.get_llm_adapter = original_adapter, original_legacy
        with budget._connect() as db:
            db.execute("UPDATE guard_runs SET status=? WHERE mode='load'", (status,))
        durable_json(
            run_dir / "execution-summary.json",
            {
                "status": status,
                "stage": "load",
                "mode": "shadow",
                "historical_provider_calls": 22,
                "accounting": budget.snapshot(),
                "calls": session.receipts(),
                "http_observations": wrapper.observations if wrapper else {},
                "command": command,
                "release_approved": False,
                "aliases_promoted": False,
            },
        )


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--goal-dir", required=True, type=Path)
    parser.add_argument("--successor-authorization", type=Path)
    parser.add_argument("--predecessor-goal", type=Path)
    parser.add_argument("--disabled-score", required=True, type=Path)
    parser.add_argument("--disabled-observations", required=True, type=Path)
    parser.add_argument("--primary-score", required=True, type=Path)
    parser.add_argument("--shadow-score", required=True, type=Path)
    parser.add_argument("--shadow-record", required=True, type=Path)
    parser.add_argument("--key-env-file", type=Path)
    parser.add_argument("--staging-env-file", type=Path)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.key_env_file is not None or args.staging_env_file is not None:
            from dotenv import dotenv_values

            if args.key_env_file is not None:
                key = dotenv_values(args.key_env_file).get("OPENROUTER_API_KEY")
                require(isinstance(key, str) and bool(key), "Designated dotenv lacks provider key")
                os.environ["OPENROUTER_API_KEY"] = key
            if args.staging_env_file is not None:
                secret = dotenv_values(args.staging_env_file).get("KNICKSIQ_STAGING_IP_HASH_SECRET")
                require(
                    isinstance(secret, str) and bool(secret),
                    "Staging dotenv lacks established client identity",
                )
                os.environ["IP_HASH_SECRET"] = secret
            get_settings.cache_clear()
        asyncio.run(run(args))
    except BaseException as exc:
        print(
            json.dumps({"status": "denied_or_stopped", "error_type": type(exc).__name__}),
            flush=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
