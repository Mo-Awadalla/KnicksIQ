# Approved service evaluation

Back to the [evaluation guide](evaluation.md).

Real provider traffic requires an explicit operator intent and credentials.
`evaluation-budget-approval-v4` is separate from gold-label approval.
It binds the evaluation identity, candidate commit and source-worktree digest, exact upstream,
model, attempt cap and aggregate dollar bound. Older approvals cannot authorize a run.
The digest covers relevant tracked and untracked executable source and dependency configuration,
including dirty changes, but excludes credentials, generated graphs and release evidence.
Relevant source symlinks are refused rather than followed outside the candidate worktree.
Preparation, preflight and candidate startup must see the same candidate; source drift requires
a fresh operator approval. The approval and run summary report the commit, digest and dirty flag,
not source contents or local source paths. Git and a valid commit are required.
The current verified profile permits at most $2 and 720 upstream attempts.
It disables reasoning and enforces provider price ceilings.
Before HTTP, the ledger reserves the published model input context plus the output ceiling.
Only valid prompt and completion token counters release the unused reservation.
Missing usage and failed calls keep their full reservation.
An attempt ceiling alone is not a dollar bound.

The funding check normalizes provider URLs and permits exemptions only for local fakes.
An empty or unverifiable account stops before the candidate acquires its authority.

Prepare the content-bound artifact with `--profile service --prepare-approval "$INTENT"`
and `--approval "$APPROVAL"`, using the same database, mapping and expectations arguments.
Then run `--profile service --approval "$APPROVAL" --redis-url "$LOCAL_REDIS"`.
The Redis URL must also be loopback.
The driver reads the provider key from `KNICKSIQ_EVAL_PROVIDER_KEY`, never from `.env`.

The evaluation-only entrypoint binds a durable ledger before readiness.
Admission is persisted before HTTP. Failures consume attempts and refusals never reach the wire.
A new output directory or restarted process cannot reset either limit.
Shutdown seals and attests a claimed ledger even if collection fails or is interrupted.
Exhausted or unverifiable runs fail instead of publishing successful service evidence.

A signed live challenge must verify before the first analyst POST.
Every response then proves its own exact request, response and HTTP status.
The v5 run configuration binds the candidate identity, Ed25519 public key and spend profile.
The private seed travels only in candidate memory and `EVAL_RUN_PROOF_KEY`.
Never publish that seed or operational configs containing private filesystem paths.
Offline scoring re-verifies every row from the bound public key.
Missing, changed, replayed or foreign proofs receive no metric credit.

Logical model stages and upstream attempts are distinct and are never compared as equals
or ordered counts. A loopback fake proves boundary behavior only.
Its `local_fake` scope always blocks provider-quality promotion.

```bash
uv run --frozen --package knicksiq-api python tools/release/eval_scenarios.py
```

These adversarial scenarios are synthetic integrity checks, not release measurements.
The 50 original semantic cases receive route-aware behavior scoring.
The separate narrative corpus requires source-first document labels and actual hybrid traces.
Owner approval and a successful funded provider run remain separate release requirements.
