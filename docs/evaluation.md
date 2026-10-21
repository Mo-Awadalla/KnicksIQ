# Answer and retrieval evaluation

The launch evaluation set is a human-reviewed JSONL artifact kept with the private release inputs.
Each case contains a paraphrased question, capability category, canonical answer facts, allowed
entity names, required claim-level citations and expected refusal status.

## Honest scoring

`tools/release/analyst_scoring.py` replaces the old phrase-match screen. It checks structure
first, then facts:

- `refused`, `degraded`, `warnings` and `llm_validated` are read before any phrase check;
- every number in a factual sentence must appear in a cited claim value or receipt;
- entities must be in the question scope;
- a decline that still asserts a fact is checked like an answer;
- a question echoed back, or a clarification counted as an answer, fails an answerable question;
- `hedged_causal` catches a hedge plus causal or predictive language;
- `required_facts`, `required_entities` and `required_phrases` must be present.

The scorer reports `meets_expectation` and `claim_backed_meets_expectation` separately. Claim
backing is the strong mode. Offline artifacts without claim values use a question-scoped archive
index and are labelled weaker.

The held-out set is `apps/api/app/evaluation/heldout_questions.jsonl`: 60 questions across nine
exact statistics, nine date ranges, eight comparisons, eight aliases and typos, eight single-game
narratives, eight turning points and ten unsupported. Labels are generated from the active release
with no model input. Nobody may tune against individual items; only the scorer report may guide
changes.

## Current measured baselines

These are baselines, not release-gate passes.

| Set | Questions | Honest pass | Notes |
| --- | ---: | ---: | --- |
| Committed 70 responses, offline rescore | 70 | 21 | No claim values in the old artifact; scoped index only. |
| Held-out set, live provider | 60 | 5 | Run before the correctness fixes; 45 review rejections and 8 provider failures. |
| Independent SQL audit of audited responses | 36 | 0 incorrect | 28 correct, 4 appropriate declines, 4 missed declines, 0 unsupported. |

The audit recomputes every number from the restored release with independent SQL. It found zero
incorrect and zero unsupported figures. It also confirmed that the archive has 46,500 play-by-play
rows and period scores for all 101 games, so answers that denied quarter or play-by-play coverage
were wrong.

## Release gates

Release gates remain:

- 100% canonical numeric and entity correctness on audited responses;
- at least 95% honest pass rate on the committed and held-out paraphrases, with claim-backed
  evidence;
- at least 95% Recall@5 for semantic questions;
- 100% correct handling of unsupported requests: instruction override, wagering and out-of-archive
  dates by pre-model refusal; live, injury, trade and prediction by analyst decline or coverage
  explanation;
- analyst p95 latency below four seconds;
- measured cost and monthly capacity at the $2 cutoff.

The quality and latency gates are not met by the current evidence. The held-out baseline is 5/60.
Measured latency is p50 2,290 ms and p95 4,608 ms on 40 questions. The independent audit supports
the factual correctness of the responses it reviewed but does not replace the held-out quality
gate. Promotion requires owner sign-off on the recorded exception or further work.

Cost and capacity are measured at $2: mean $0.001415 per question and about 1,413 questions per
month on current routing. Routing is unpinned, so the practical range is about 1,200 to 1,400.
See `release-evidence/llm-primary-20261021/cost/README.md`.

## Offline harness

The committed candidate set is
`apps/api/app/evaluation/questions.jsonl`. It contains 120 questions in the requested category
distribution. New entries start with `label_status: needs_archive_review`: a reviewer must pin the
data release, add canonical `required_facts` and map `relevant_evidence_ids` from the archive. Web
pages may suggest high-value questions, but web claims are not gold labels.

Run the set against a non-production API, because production responses omit the debug route,
evidence and tool trace:

```bash
uv run python -m app.evaluation.cli \
  apps/api/app/evaluation/questions.jsonl \
  --base-url http://127.0.0.1:8000 \
  --output evaluation-report.json
```

The report contains routing accuracy, relevant evidence Recall@5 and Recall@20, exact numeric
correctness, citation correctness, answer completeness, correct abstention, p50 and p95 latency,
and LLM calls and cost per query.

The retrieval trace exposes `candidate_evidence_ids` before reranking and
`returned_evidence_ids` after selection. The report classifies a case as `reranking_may_help` when
relevant evidence is in the top 20 but absent from the top 5. It classifies it as `retrieval_miss`
when relevant evidence is absent from the top 20; that points to parsing, indexing, filtering or
chunking instead of the reranker.

Shadow evaluation records only request ID, mode, intent, dependency outcome, candidate validation
result, retrieval count, latency and model, prompt and data versions. It does not retain questions,
answers, evidence text or claim comparisons. The intended launch mode and its single authoritative
statement are in
[the release checklist](release-checklist.md#intended-launch-configuration).
