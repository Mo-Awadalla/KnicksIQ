# Answer and retrieval evaluation

The launch evaluation set is a human-reviewed JSONL artifact kept with the private release inputs. Each case contains a paraphrased question, capability category, canonical answer facts, allowed entity names, required claim-level citations, and expected refusal status.

Release gates are: 100% canonical numeric/entity correctness; at least 95% overall paraphrase and citation pass rate; at least 95% Recall@5 for semantic questions; and 100% explicit refusal for unsupported tactical, live, injury, trade, future, or non-archive claims. Tests run once with Qdrant enabled and again with Qdrant, Redis, and OpenRouter disabled. The deterministic answer must remain correct in both runs.

Shadow evaluation records only request ID, mode, intent, dependency outcome,
candidate validation result, retrieval count, latency, and model/prompt/data
versions. It does not retain questions, answers, evidence text, or claim
comparisons. Promotion to `llm_primary` requires the release gates plus analyst
p95 below four seconds and errors below one percent.

## Fixed-cohort release execution

Use `app.evaluation.release_runner` with the frozen 120-case contract and its
separate hash-bound owner approval. All 50 original semantic cases remain in the
enabled retrieval denominator; a clarification does not substitute for a ranked
retrieval trace. The runner captures the analyst execution being scored.

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
