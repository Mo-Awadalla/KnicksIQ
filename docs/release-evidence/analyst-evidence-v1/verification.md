# Evidence-loop verification — 2026-09-21

Implementation is opt-in and has not been promoted or deployed.

- Python regression suite: **331 passed** (`uv run pytest -q`).
- New contract/integration suite: **20 passed**, including the six-turn protocol,
  full-answer rejection and repair, release/scope changes, missing coverage,
  complete catalog baselines, actual Redis races, revision conflicts, replay,
  atomic budget limits and stateless failure behavior.
- Ruff and Pyright: pass.
- Frontend TypeScript/build: pass.
- Targeted browser tests: five passed across conversation context, analytics
  receipts, and preservation of turn identity during network retries.
- Knowledge graph refreshed with AST-only `graphify update .`.

These tests use scripted provider responses and synthetic archive fixtures. They
are evidence of protocol/calculation behavior, **not** evidence of real-model
accuracy, naturalness or latency.

The initial OpenRouter probe used `nvidia/nemotron-3-ultra-550b-a55b:free` and
returned HTTP 404 because its endpoint did not match the enforced privacy and
structured-output constraints. The follow-up configuration allows provider data
collection, uses `nex-agi/nex-n2.5-mini:free`, and passed Action, ProposedAnswer
and AnswerReview probes in strict JSON-schema mode. Calls used an isolated local
Redis evaluation ledger; production spending state was not reset.

Still blocked/unreviewed: actual-provider six-turn conversation repeated five
times, held-out human-labelled reviewer calibration,
search Recall@5, real answer completion, delivery rubric, warm ordinary p95,
shadow evaluation and existing release approval. Draft development/held-out
fixtures are explicitly not human-reviewed. None of these release gates is claimed
as passed, and the default rollout flag remains false.
