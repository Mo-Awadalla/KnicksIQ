"""Shared plumbing for the budget and service-profile scenarios.

One loopback fake wire, one approval builder that seals exactly as the operator
does, one throwaway driver runner, and small ledger accessors. Nothing here
talks to a provider, Redis, Qdrant or PostgreSQL.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from eval_scenario_fixtures import dump, load
from eval_scenario_support import clean_env

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from app.evaluation.attempt_ledger import read_records  # noqa: E402
from app.evaluation.candidate_proof import RunProofKey  # noqa: E402
from app.evaluation.provider_approval import approval_payload, load_approval  # noqa: E402
from app.evaluation.provider_guard import RunBinding, issue_run_binding  # noqa: E402
from app.evaluation.spend_bound import SpendBound  # noqa: E402

APPROVED_AT = "2026-10-30T00:00:00Z"
MODEL = "local-fake"
IDENTITY = "a" * 64
LABELS = "b" * 64
CASES = 120

PREAMBLE = """
import json
from app.evaluation.provider_guard import bind_run_guard, require_run_guard
from app.evaluation.attempt_ledger import AttemptLedger
from app.services.report_llm import OpenAICompatibleLLMAdapter


def adapter(base_url, model, max_tokens=8):
    return OpenAICompatibleLLMAdapter(
        base_url=base_url, api_key="local-fake", model=model, max_tokens=max_tokens
    )
"""


class Wire(BaseHTTPRequestHandler):
    """A loopback OpenAI-compatible wire that counts every request it serves."""

    status = 200

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.server.hits.append(self.path)  # type: ignore[attr-defined]
        if self.status == 200:
            body = json.dumps(
                {
                    "id": "fake-1",
                    "model": MODEL,
                    "choices": [{"message": {"content": "{}"}}],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                        "cost": 0,
                    },
                }
            ).encode()
        else:
            body = b'{"error":{"message":"upstream failed"}}'
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        return


@contextmanager
def wire(*, status: int = 200) -> Iterator[tuple[str, list[str]]]:
    handler = type("StatusWire", (Wire,), {"status": status})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.hits = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1", server.hits  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()


_PROOF_KEYS: dict[str, RunProofKey] = {}


def spend_for_scenarios() -> SpendBound:
    return SpendBound.from_dict(
        {
            "max_total_nano_usd": 2_000_000_000,
            "model_context_tokens": 1_048_576,
            "max_completion_tokens": 1200,
            "prompt_nano_usd_per_token": 45,
            "completion_nano_usd_per_token": 500,
            "provider_tags": ["open-inference/fp4", "morph/fp8", "baidu/fp8", "wafer/us"],
            "pricing_sha256": "1" * 64,
            "endpoints_sha256": "2" * 64,
        }
    )


def proof_key_for(binding: RunBinding) -> RunProofKey:
    """The in-memory key pair this run was issued with; a scenario signs as the candidate.

    The private half exists only in this process, exactly as the operator's parent process
    holds it for a real run, and is never written to an artifact.
    """
    try:
        return _PROOF_KEYS[binding.run_id]
    except KeyError as exc:
        raise AssertionError(f"run {binding.run_id} was built without a proof key") from exc


def approval_for(
    directory: Path,
    *,
    base_url: str,
    cap: int = 8,
    model: str = MODEL,
    identity: str = IDENTITY,
    labels: str = LABELS,
    cases: int = CASES,
) -> tuple[Any, RunBinding]:
    """Build, seal and verify one approval exactly as the operator would."""
    payload = approval_payload(
        approved=True,
        approver="operator",
        approved_at=APPROVED_AT,
        identity_sha256=identity,
        labels_sha256=labels,
        case_count=cases,
        provider_base_url=base_url,
        provider_model=model,
        max_provider_requests=cap,
        reasoning_effort="none",
        spend_bound=spend_for_scenarios(),
        ledger_root=str(directory / "ledger"),
    )
    path = dump(directory / "approval.json", payload)
    approval = load_approval(path, identity_sha256=identity, labels_sha256=labels, case_count=cases)
    binding, key = issue_run_binding(approval)
    _PROOF_KEYS[binding.run_id] = key
    return approval, binding


def issue(directory: Path, binding: RunBinding, name: str) -> tuple[Path, str]:
    path = directory / name / "run-config.json"
    return path, binding.write(path)


def driver(
    directory: Path, name: str, body: str, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a throwaway driver inside this scenario's directory, never in the repository."""
    path = directory / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    environment = clean_env()
    environment.update(env or {})
    return subprocess.run(
        [sys.executable, str(path)],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def reported(result: subprocess.CompletedProcess[str], problems: list[str]) -> dict[str, Any]:
    if result.returncode != 0:
        problems.append(f"driver failed: {result.stderr[-1200:]}")
        return {}
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        problems.append(f"driver printed no result: {result.stdout[-600:]}")
        return {}


def kinds(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in read_records(path):
        counts[record.kind] = counts.get(record.kind, 0) + 1
    return counts


def attempts(path: Path) -> list[Any]:
    return [record for record in read_records(path) if record.kind == "admitted"]


def sealed(binding: RunBinding) -> None:
    binding.ledger().seal()


__all__ = [
    "APPROVED_AT",
    "spend_for_scenarios",
    "CASES",
    "IDENTITY",
    "LABELS",
    "MODEL",
    "PREAMBLE",
    "approval_for",
    "attempts",
    "driver",
    "dump",
    "issue",
    "kinds",
    "load",
    "reported",
    "sealed",
    "wire",
]
