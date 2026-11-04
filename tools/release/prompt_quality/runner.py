"""Run the approved KnicksIQ evaluation through the real ASGI application."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import multiprocessing
import os
import random
import subprocess
import sys
import time
import urllib.error
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

FLOW_DIR = Path(__file__).resolve().parent
PROJECT = FLOW_DIR.parents[2]
MODEL = "deepseek-v4.1-flash"
BASE_URL = "https://opencode.ai/inference/go/openai/v1"
RELEASE = "2025-26.20260928.1"
CASE_TIMEOUT_SECONDS = 180
MAX_ATTEMPTS = 2


class TrialError(Exception):
    def __init__(self, failure_class: str):
        self.failure_class = failure_class
        super().__init__(failure_class)


def credential() -> str:
    try:
        proc = subprocess.run(
            ["opencode", "auth", "export"], capture_output=True, text=True,
            check=True, timeout=20,
        )
        entries = json.loads(proc.stdout)
        keys = [entry["value"]["key"] for entry in entries
                if entry.get("integrationID") == "opencode-go" and entry.get("active")]
        if len(keys) != 1 or not isinstance(keys[0], str) or not keys[0]:
            raise ValueError("expected one active Go credential")
        return keys[0]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise TrialError("credential_error") from exc


def configure(key: str) -> None:
    # Never inherit the application's production database or session store.
    db_url = os.environ.get("RATCHET_DB_URL", "")
    redis_url = os.environ.get("RATCHET_REDIS_URL", "redis://127.0.0.1:56389/0")
    try:
        database, sessions = urlsplit(db_url), urlsplit(redis_url)
        local_hosts = {"127.0.0.1", "localhost", "::1"}
        valid = (
            database.scheme == "postgresql+asyncpg" and database.hostname in local_hosts
            and sessions.scheme == "redis" and sessions.hostname in local_hosts
        )
    except ValueError:
        valid = False
    if not valid:
        raise TrialError("explicit_loopback_configuration_required")
    os.chdir(PROJECT)
    os.environ.update({
        "DB_URL": db_url,
        "REDIS_URL": redis_url,
        "ENVIRONMENT": "development", "TEST_MODE": "false", "SEED_ON_STARTUP": "false",
        "AI_PROVIDER": "opencode", "AI_BASE_URL": BASE_URL,
        "AI_API_KEY": key, "AI_CHAT_MODEL": MODEL, "AI_REASONING_EFFORT": "none",
        "OPENROUTER_ALLOWED_MODELS": json.dumps([MODEL]),
        "ANALYST_EVIDENCE_LOOP_ENABLED": "true", "ANALYSIS_ANSWER_MODE": "llm_primary",
        "REQUIRE_ACTIVE_RELEASE": "true", "RAG_QDRANT_ENABLED": "false",
        "PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE": "100000", "PUBLIC_CHAT_RATE_LIMIT_PER_DAY": "1000000",
        "SENTRY_DSN": "", "LOG_LEVEL": "CRITICAL",
    })
    sys.path.insert(0, str(PROJECT / "apps" / "api"))
    sys.path.insert(0, str(FLOW_DIR))
    logging.disable(logging.CRITICAL)


def summed_usage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    total: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0}
    billing = {"cost": 0.0, "list_cost": 0.0, "allowance": 0.0}
    for call in calls:
        usage = call.get("usage")
        if not isinstance(usage, dict):
            raise TrialError("missing_usage")
        for destination, source in (("input_tokens", "prompt_tokens"),
                                    ("output_tokens", "completion_tokens")):
            value = usage.get(source)
            if type(value) is not int or value < 0:
                raise TrialError("missing_usage")
            total[destination] += value
        opencode = usage.get("opencode")
        if not isinstance(opencode, dict) or opencode.get("billing_source") != "go":
            raise TrialError("missing_billing_usage")
        for target, source, field in (("cost", usage, "cost"),
                                      ("list_cost", opencode, "list_cost"),
                                      ("allowance", opencode, "allowance")):
            value = source.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise TrialError("missing_billing_usage")
            billing[target] += value
    if not calls:
        raise TrialError("missing_model_call")
    total["provider_billing"] = billing
    return total


async def run_trial(case: dict[str, Any], prefix_questions: list[str], induce_error: bool) -> dict[str, Any]:
    configure(credential() if not induce_error else "induced-error-no-credential")
    from app.main import create_app
    from app.services import report_llm
    from grader import grade_case
    from httpx import ASGITransport, AsyncClient
    from app.services.analyst_loop import AnalystLoop

    calls: list[dict[str, Any]] = []
    provider_errors: list[str] = []
    session_id = "knicksiq-ratchet-" + uuid.uuid4().hex
    original_open = report_llm._open_provider
    original_generate = report_llm.OpenAICompatibleLLMAdapter.generate
    execution_failures: list[str] = []
    original_investigate = AnalystLoop.investigate

    async def instrumented_investigate(loop: Any) -> Any:
        try:
            return await original_investigate(loop)
        except BaseException as exc:
            tb = exc.__traceback__
            while tb is not None and tb.tb_next is not None:
                tb = tb.tb_next
            location = f":{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}" if tb else ""
            if isinstance(exc, ValueError) and str(exc) in {
                "Required review/action context exceeds input budget",
                "Required model input exceeds budget",
            }:
                execution_failures.append("input_budget_exceeded")
            else:
                execution_failures.append(type(exc).__name__ + location)
            raise

    AnalystLoop.investigate = instrumented_investigate

    def instrumented_open(request: Any, *, guarded: bool, timeout: float) -> Any:
        request.add_header("User-Agent", "knicksiq-ratchet/1.0")
        request.add_header("x-opencode-session", session_id)
        if induce_error:
            raise urllib.error.HTTPError(request.full_url, 503, "induced", {}, None)
        return original_open(request, guarded=guarded, timeout=timeout)

    async def instrumented_generate(adapter: Any, *, system: str, user: str) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            output = await original_generate(adapter, system=system, user=user)
        except Exception as exc:
            provider_errors.append(type(exc).__name__)
            raise
        metadata = adapter.last_metadata
        calls.append({"model": metadata.get("model"), "usage": metadata.get("usage"),
                      "messages": messages, "output": output})
        if metadata.get("model") != MODEL:
            provider_errors.append("served_model_mismatch")
            raise TrialError("served_model_mismatch")
        return output

    report_llm._open_provider = instrumented_open
    report_llm.OpenAICompatibleLLMAdapter.generate = instrumented_generate
    app = create_app()
    turns: list[dict[str, Any]] = []
    token = None
    revision = 0
    started = time.monotonic()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=60) as client:
            for question in [*prefix_questions, case["question"]]:
                first_call = len(calls)
                request = {"question": question, "season": "2025-26",
                           "turn_id": "ratchet-" + uuid.uuid4().hex, "expected_revision": revision}
                if token is not None:
                    request["session_token"] = token
                response = await client.post("/analysis/query", json=request)
                if provider_errors:
                    raise TrialError("served_model_mismatch" if "served_model_mismatch" in provider_errors
                                     else "provider_error")
                if response.status_code != 200:
                    raise TrialError("api_http_" + str(response.status_code))
                body = response.json()
                if body.get("data_version") != RELEASE:
                    raise TrialError("unexpected_release")
                if not body.get("state_committed") or not body.get("session_token"):
                    raise TrialError("session_unavailable")
                if body.get("degraded"):
                    warnings = " ".join(body.get("warnings") or []).lower()
                    if "evidence review" not in warnings and not (
                        execution_failures and set(execution_failures) == {"input_budget_exceeded"}
                    ):
                        raise TrialError("infrastructure_fallback:" + "|".join(execution_failures or ["budget_or_admission"]))
                if not isinstance(body.get("answer"), str) or not body["answer"].strip():
                    raise TrialError("empty_response")
                turns.append({"question": question, "request": request, "response": body,
                              "call_range": [first_call, len(calls)]})
                token, revision = body["session_token"], body["revision"]
    usage = summed_usage(calls)
    latency = time.monotonic() - started
    # Grader owns a separate transport; candidate instrumentation ends before grading.
    report_llm._open_provider = original_open
    report_llm.OpenAICompatibleLLMAdapter.generate = original_generate
    try:
        grade = await grade_case(case, turns, calls)
    except Exception as exc:
        raise TrialError("grader_error") from exc
    if not isinstance(grade, dict) or not isinstance(grade.get("grade"), dict):
        raise TrialError("invalid_grader_result")
    if grade.get("judge_model") != "glm-5.3-flash" or not grade.get("judge_usage"):
        raise TrialError("invalid_grader_metadata")
    grade["grade"]["input_budget_ok"] = int("input_budget_exceeded" not in execution_failures)
    if not grade["grade"]["input_budget_ok"]:
        grade["explanation"] += "; application input budget exceeded; graded the delivered fallback, not the abandoned model draft"
    trace = []
    for turn in turns:
        trace.append({"role": "user", "content": turn["question"]})
        start, end = turn["call_range"]
        for call in calls[start:end]:
            trace.extend(call["messages"])
            trace.append({"role": "assistant", "content": call["output"]})
        trace.append({"role": "tool_result", "name": "analysis_evidence",
                      "content": json.dumps({key: turn["response"].get(key)
                                             for key in ("evidence", "citations", "tool_calls",
                                                         "warnings", "data_version")},
                                            ensure_ascii=False)})
        trace.append({"role": "assistant", "content": turn["response"]["answer"]})
    return {"grade": grade, "usage": usage, "latency_s": latency, "trace": trace}


def worker(connection: Any, case: dict[str, Any], prefix_questions: list[str], induce_error: bool) -> None:
    outcome: dict[str, Any]
    try:
        # The app configures structlog independently of Python logging.
        with open(os.devnull, "w", encoding="utf-8") as quiet:
            with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                result = asyncio.run(run_trial(case, prefix_questions, induce_error))
        outcome = {"result": result}
    except BaseException as exc:
        failure = exc.failure_class if isinstance(exc, TrialError) else type(exc).__name__
        outcome = {"failure_class": failure,
                   "diagnostic": str(exc.__cause__) if exc.__cause__ is not None else str(exc)}
    finally:
        root = PROJECT
        paths = set()
        for module in list(sys.modules.values()):
            filename = getattr(module, "__file__", None)
            if not filename:
                continue
            path = Path(filename).resolve()
            if path.is_relative_to(PROJECT) and path.suffix == ".py":
                relative = path.relative_to(root).as_posix()
                if relative != "apps/api/app/services/analyst_provider.py":
                    paths.add(relative)
        outcome["dependencies"] = sorted(paths)
        try:
            connection.send(outcome)
        finally:
            connection.close()


def attempt(case: dict[str, Any], prefixes: list[str], induce_error: bool, timeout: float) -> dict[str, Any]:
    ctx = multiprocessing.get_context("spawn")
    recv, send = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=worker, args=(send, case, prefixes, induce_error))
    proc.start()
    send.close()
    try:
        if not recv.poll(timeout):
            return {"failure_class": "timeout"}
        try:
            return recv.recv()
        except EOFError:
            return {"failure_class": "worker_exit"}
    finally:
        recv.close()
        if proc.is_alive():
            proc.terminate()
        proc.join(timeout=5)
        if proc.is_alive():
            proc.kill()
            proc.join()


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a nonempty list")
    ids = [row["id"] for row in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case IDs")
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--split", type=Path)
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--pilot", nargs="+")
    parser.add_argument("--induce-error", action="store_true")
    args = parser.parse_args()
    if args.reps < 1:
        parser.error("--reps must be positive")
    cases = load_cases(args.cases)
    by_id = {row["id"]: row for row in cases}
    if args.split:
        split = json.loads(args.split.read_text(encoding="utf-8"))
        train, test = split["train"], split["test"]
        all_ids = train + test
        if len(all_ids) != len(set(all_ids)) or set(all_ids) != set(by_id):
            raise ValueError("split must partition all case IDs exactly once")
        train_ids = set(train)
    elif args.pilot:
        train_ids = set(by_id)
    else:
        parser.error("--split is required outside a pilot")
    selected = set(by_id)
    if args.pilot:
        selected = {item for group in args.pilot for item in group.split(",") if item}
        if not selected or not selected <= set(by_id):
            parser.error("--pilot contains unknown or empty IDs")
    scenarios = {"interesting": by_id["knicks-01"]["question"],
                 "brunson_split": by_id["knicks-11"]["question"]}
    args.out.mkdir(parents=True, exist_ok=True)
    results_path, errors_path = args.out / "results.jsonl", args.out / "errors.jsonl"
    completed = set()
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            slot = (row["prompt_id"], row["rep"])
            if slot in completed:
                raise ValueError("duplicate result slot")
            completed.add(slot)
    for case in cases:
        if case["id"] not in selected:
            continue
        for rep in range(args.reps):
            slot = (case["id"], rep)
            if slot in completed and not args.induce_error:
                continue
            prefixes = [scenarios[name] for name in case.get("prefix_scenarios", [])]
            failures = []
            diagnostics = []
            result = None
            deadline = time.monotonic() + CASE_TIMEOUT_SECONDS
            for number in range(1, (1 if args.induce_error else MAX_ATTEMPTS) + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failures.append("timeout")
                    break
                outcome = attempt(case, prefixes, args.induce_error, remaining)
                if args.induce_error and outcome.get("dependencies"):
                    (args.out / "harness-dependencies.json").write_text(
                        json.dumps(outcome["dependencies"], indent=2) + "\n", encoding="utf-8"
                    )
                if "result" in outcome:
                    result = outcome["result"]
                    break
                failures.append(outcome["failure_class"])
                diagnostics.append(outcome.get("diagnostic"))
                if number < MAX_ATTEMPTS and not args.induce_error:
                    delay = random.uniform(0.5, 1.5) * number
                    time.sleep(min(delay, max(0, deadline - time.monotonic())))
            # Retried successes are not admissible under the strict retry policy.
            if failures or result is None:
                append_jsonl(errors_path, {"prompt_id": case["id"], "rep": rep,
                                           "failure_class": failures[-1] if failures else "unknown",
                                           "attempts": len(failures) + int(result is not None),
                                           "failures": failures, "variant": args.variant})
                if args.pilot:
                    print(json.dumps({"prompt_id": case["id"], "diagnostic": diagnostics}), flush=True)
                print(json.dumps({"prompt_id": case["id"], "rep": rep, "status": "error",
                                  "failure_class": failures[-1] if failures else "unknown"}), flush=True)
                continue
            judged = result["grade"]
            row = {"prompt_id": case["id"], "rep": rep, "prompt": case["question"],
                   "tags": [case["tag"]], "grade": judged["grade"],
                   "status": "ok", "model": MODEL,
                   "usage": result["usage"], "latency_s": result["latency_s"],
                   "judge_model": judged["judge_model"], "judge_usage": judged["judge_usage"]}
            if case["id"] in train_ids:
                row["explanation"] = judged.get("explanation", "")
                trace_dir = args.out / "traces"
                trace_dir.mkdir(exist_ok=True)
                (trace_dir / f"{case['id']}_rep{rep}.json").write_text(
                    json.dumps(result["trace"], ensure_ascii=False), encoding="utf-8")
            append_jsonl(results_path, row)
            completed.add(slot)
            print(json.dumps({"prompt_id": case["id"], "rep": rep, "grade": row["grade"]}), flush=True)


if __name__ == "__main__":
    main()
