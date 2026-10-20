# Answer and retrieval evaluation

The launch evaluation set is a human-reviewed JSONL artifact kept with the private release inputs. Each case contains a paraphrased question, capability category, canonical answer facts, allowed entity names, required claim-level citations, and expected refusal status.

Release gates are: 100% canonical numeric/entity correctness; at least 95% overall paraphrase and citation pass rate; at least 95% mean Recall@k for semantic questions; and 100% explicit refusal for unsupported tactical, live, injury, trade, future, or non-archive claims. Tests run once with Qdrant enabled and again with Qdrant, Redis, and OpenRouter disabled. The deterministic answer must remain correct in both runs.

Recall@k follows each question's scope. For semantic answer cases, it is the share of reviewed
targets found among the top k evidence references returned by actual analyst searches, with
k = max(5, number of targets). A target list is never capped.

For semantic clarification cases, reviewers record every candidate game listed in the answer as
canonical IDs in `listed_candidate_game_ids`. Recall@k is computed over that list. Incomplete
lists receive partial credit; any listed non-target game scores zero for the case. Clarifications
do not require a ranked search trace because the analyst may clarify before retrieval.

A context-free clarification ("that game" with no earlier game) must have empty conversation
context and no targets. It scores 1 only when a valid, supported review finds a clarification,
lists no candidate game, and the analyst produced no candidate or returned search evidence. The
metric keeps its `semantic_recall_at_5` key in scored artifacts and the release gate.

The release gate has no shadow stage. Launch goes straight to `llm_primary`
(owner decision, 2026-10-20). Launch requires the release gates plus analyst
p95 below 15 seconds and errors below one percent. The owner relaxed this from four
seconds on 2026-10-19: each model answer makes two or three sequential provider calls, and
the measured p95 at concurrency 10 was 10.5 seconds against a 30-second request deadline.

The executable readiness gate applies the same strict bound: 15,000 ms is blocked.
Archive p95 must still be below 1,000 ms at concurrency 10, with errors below 1%.
These local policy checks do not replace the hosted cold-start and latency checks
in [the deployment guide](render-deploy.md).

## Fixed-cohort release execution

Use `app.evaluation.release_runner` with the frozen 120-case contract and its
separate hash-bound owner approval. All 50 original semantic cases remain in
the fixed cohort. Answer cases require ranked retrieval traces; semantic
clarifications use the output-bound candidate-game review instead. A
context-free clarification must have no retrieval candidates or returned
evidence. The runner captures the analyst execution being scored.

Primary and shadow collection require an explicit `CountedRun`. Its environment
verifier receives the selected database scheme, host, port and name, without
credentials. It must verify the exact isolated staging binding, candidate,
dependencies and real monthly accounting before application execution. Hosted
databases are admitted only through this verifier; providing metadata or an
approval boolean is not isolation proof. Every provider request additionally
requires current conservative pricing verification and durable cumulative caps.
The CLI supplies no default paid-execution verifier.

Service-disabled collection remains local-database-only, with Qdrant, Redis,
the provider and telemetry disabled. It permits zero paid requests. Keep all
expectations, approvals, captures, source mappings and reviews in private local
evidence; final scoring requires complete output-bound assertion review.

## Hosted browser routing evidence

Backend CI installs Redis so the SQL/HTTP/Redis reservation, shadow, replay and
retrieval-trace regressions execute on Ubuntu instead of skipping for a missing
server binary.

Hosted CI retains the `browser-network-evidence` artifact for 14 days. Its
synthetic Playwright report includes `network-destinations` attachments with
allowed origins, requested destinations and blocked requests. This verifies
fixture-routing controls, not hosted staging connectivity or model quality.
Private release inputs and evaluation artifacts are not uploaded.

## Development diagnostic harness

The diagnostic harness below is not the frozen release runner and cannot replace
its owner-approved contract, assertion review or release evidence.

The committed candidate set is
`apps/api/app/evaluation/questions.jsonl`. It contains 120 questions in the
requested category distribution. New entries deliberately start with
`label_status: needs_archive_review`: a reviewer must pin the data release, add
canonical `required_facts`, and map `relevant_evidence_ids` from the archive.
Web pages may suggest high-value questions, but web claims are not gold labels.

Run the set against a non-production API, because production responses omit the
debug route, evidence, and tool trace:

```bash
uv run python -m app.evaluation.cli \
  apps/api/app/evaluation/questions.jsonl \
  --base-url http://127.0.0.1:8000 \
  --output evaluation-report.json
```

The report contains only actionable metrics: routing accuracy, relevant
evidence Recall@5 and Recall@20, exact numeric correctness, citation
correctness, answer completeness, correct abstention, p50/p95 latency, and LLM
calls/cost per query.

The retrieval trace exposes `candidate_evidence_ids` before reranking and
`returned_evidence_ids` after selection. The report classifies a case as
`reranking_may_help` when relevant evidence is in the top 20 but absent from
the top 5. It classifies it as `retrieval_miss` when relevant evidence is absent
from the top 20; that points to parsing, indexing, filtering, or chunking
instead of the reranker.
