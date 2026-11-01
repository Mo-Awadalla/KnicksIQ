"""Candidate-proof protocol scenarios: what the signature binds and when it is refused.

Both scenarios run the real proof code: the real Ed25519 signer, the real ASGI
proof surface, the real collector. No provider, PostgreSQL, Redis or Qdrant is
contacted; the run's upstream is a loopback fake, so its scope is ``local_fake``.

Run: uv run --package knicksiq-api python tools/release/eval_scenarios.py proof_protocol_roundtrip
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.evaluation.candidate_proof import (
    CHALLENGE_HEADER,
    PREFLIGHT_PATH,
    PROOF_HEADER,
    ProofError,
    ResponseProof,
    canonical_digest,
    challenge_payload,
    generate_keypair,
    new_nonce,
)
from app.evaluation.proof_surface import CandidateProofMiddleware, signer_for
from eval_scenario_fixtures import write_dataset
from eval_scenario_support import expect
from eval_scenarios_budget_support import (
    CASES,
    IDENTITY,
    LABELS,
    approval_for,
    driver,
    issue,
    proof_key_for,
    reported,
)
from eval_scenarios_proof_support import call_asgi, signer_of, signing_candidate
from eval_scenarios_service_support import service_collect, synthetic_identity


def scenario_proof_protocol_roundtrip(directory: Path) -> list[str]:
    """The real signer, the real wrapper and a mismatched key: prove, challenge, refuse."""
    problems: list[str] = []
    key = generate_keypair()
    other = generate_keypair()
    if key.public_key == other.public_key:
        problems.append("two generated key pairs share a public key")
    _, binding = approval_for(
        directory, base_url="http://127.0.0.1:9/v1", cap=4, identity=IDENTITY, labels=LABELS
    )
    signer = signer_of(binding, proof_key_for(binding))
    nonce = new_nonce()
    proof = signer.sign(
        kind="response",
        nonce=nonce,
        request_sha256=canonical_digest({"question": "q"}),
        http_status=200,
        response_sha256=canonical_digest({"answer": "a"}),
    )
    proof.verify(binding.proof_public_key)
    tampered = proof.as_dict()
    tampered["response_sha256"] = canonical_digest({"answer": "tampered"})
    try:
        ResponseProof.from_dict(tampered).verify(binding.proof_public_key)
    except ProofError:
        pass
    else:
        problems.append("a tampered statement still verified")
    try:
        proof.verify(other.public_key)
    except ProofError:
        pass
    else:
        problems.append("a proof verified against a key that did not sign it")
    for label, environ in (
        ("without a key", {}),
        ("with another run's key", {"EVAL_RUN_PROOF_KEY": other.private_key}),
    ):
        try:
            signer_for(binding, environ)
        except ProofError:
            continue
        problems.append(f"the entrypoint accepted the run {label}")

    served: list[dict[str, Any]] = []

    async def downstream(scope: dict[str, Any], receive: Any, send: Any) -> None:
        message = await receive()
        body = json.loads(message["body"] or b"{}")
        served.append(body)
        payload = {"answer": "Synthetic.", "outcome": "clarify", "request_id": body["turn_id"]}
        encoded = json.dumps(payload).encode()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": encoded})

    wrapped = CandidateProofMiddleware(downstream, signer)
    status, _, body = call_asgi(wrapped, path="/analysis/query", body={"turn_id": "t"})
    if status != 400 or served:
        problems.append(f"an unchallenged analyst request must be refused first: {status}")
    elif body.get("error", {}).get("code") != "evaluation_challenge_required":
        problems.append(f"the refusal must name the missing challenge: {body}")

    challenged = new_nonce()
    sent = {"turn_id": "t", "question": "q"}
    status, headers, body = call_asgi(
        wrapped,
        path="/analysis/query",
        body=sent,
        headers=[(CHALLENGE_HEADER.encode(), challenged.encode())],
    )
    if status != 200 or len(served) != 1:
        problems.append(f"a challenged analyst request is served: {status}")
    elif PROOF_HEADER not in headers:
        problems.append("the served response carries no candidate proof")
    else:
        served_proof = ResponseProof.from_header(headers[PROOF_HEADER])
        served_proof.verify(binding.proof_public_key)
        if served_proof.nonce != challenged:
            problems.append("the response proof does not echo the challenge nonce")
        if served_proof.response_sha256 != canonical_digest(body):
            problems.append("the response proof does not bind the body it was sent with")
        if served_proof.request_sha256 != canonical_digest(sent):
            problems.append("the response proof does not bind the request it answered")
        if served_proof.config_sha256 != binding.config_sha256:
            problems.append("the response proof does not bind the run configuration")

    challenge = challenge_payload(
        nonce=new_nonce(),
        run_id=binding.run_id,
        config_sha256=binding.config_sha256,
        scope=binding.scope,
    )
    status, headers, body = call_asgi(wrapped, path=PREFLIGHT_PATH, body=challenge)
    if status != 200 or PROOF_HEADER not in headers:
        problems.append(f"the preflight is answered with a proof: {status} {body}")
    else:
        preflight = ResponseProof.from_header(headers[PROOF_HEADER])
        preflight.verify(binding.proof_public_key)
        if preflight.kind != "preflight" or preflight.nonce != challenge["nonce"]:
            problems.append("the preflight proof is not this challenge")
        if preflight.request_sha256 != canonical_digest(challenge):
            problems.append("the preflight proof does not bind its challenge")
        if preflight.response_sha256 != canonical_digest(body):
            problems.append("the preflight proof does not bind its own answer")
    status, _, _ = call_asgi(
        wrapped, path=PREFLIGHT_PATH, body=dict(challenge, run_id="run-someone-else")
    )
    if status == 200:
        problems.append("a preflight challenge for another run was signed")
    return problems


def scenario_collect_requires_live_proof(directory: Path) -> list[str]:
    """Nothing is POSTed before a live, correctly keyed candidate proves itself."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    responses = directory / "responses.jsonl"
    identity, labels, _ = synthetic_identity(directory, questions, expectations)
    _, binding = approval_for(
        directory, base_url="http://127.0.0.1:9/v1", cap=8, identity=identity, labels=labels
    )
    key = proof_key_for(binding)
    config, announced = issue(directory, binding, "run")
    claimed = driver(
        directory,
        "claim",
        "import json\n"
        "from app.evaluation.provider_guard import bind_run_guard\n"
        "bind_run_guard()\n"
        "print(json.dumps({'claimed': True}))\n",
        env={"EVAL_RUN_CONFIG": str(config), "EVAL_RUN_CONFIG_SHA256": announced},
    )
    expect(reported(claimed, problems).get("claimed") is True, "the claim is written", problems)

    with signing_candidate(binding, key, refuse_preflight=True) as (base_url, requests_seen):
        refused = service_collect(
            directory, base_url, questions, expectations, responses, config, announced
        )
    expect(refused.returncode != 0, "a candidate that cannot preflight is refused", problems)
    expect(requests_seen == [], f"no analyst POST before a proof: {len(requests_seen)}", problems)
    expect(not responses.exists(), "a refused collection writes no responses", problems)

    with signing_candidate(binding, generate_keypair()) as (base_url, requests_seen):
        wrong = service_collect(
            directory, base_url, questions, expectations, responses, config, announced
        )
    expect(wrong.returncode != 0, "a candidate signing with another key is refused", problems)
    expect(
        requests_seen == [],
        f"a wrong-key candidate is refused before any POST: {len(requests_seen)}",
        problems,
    )
    expect(
        "proof" in (wrong.stderr or "").lower(),
        f"the refusal names the proof: {wrong.stderr[-400:]}",
        problems,
    )
    expect(CASES == 120, f"the approved identity keeps its fixed denominator: {CASES}", problems)
    return problems
