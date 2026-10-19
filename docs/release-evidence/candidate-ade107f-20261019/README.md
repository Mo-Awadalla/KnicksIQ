# Release evidence for `ade107f`, 2026-10-19

Binds the evidence that can be produced without the owner or production to the tested commit
`ade107fe17b3a8ff0e59632bd45b3826e4499068`. The generated gate view is in
`docs/release-evidence/release-record.md`. It drops from 42 failure lines to 30. It stays **BLOCKED**.

Deploy the tested commit itself. The commit that carries this record is a later docs-only commit.

## Evidence added

| Check | Source | Notes |
| --- | --- | --- |
| backend, frontend, migrations_loader, security, desktop_mobile_keyboard, accessibility | `ci-ade107f.json` | CI run 39306820629, attempt 2 |
| retrieval_targets, retrieval_filters | `index-verification.json`, `verify_index.py` | Local Qdrant 1.18 collections, not remote |
| warm_load | `warm-load-shadow.json` | Pre-promotion configuration, local restore |
| rollback targets (not `rollback_snapshot`) | `rollback-targets.json` | Read-only capture of live deployments, data version, aliases |

CI attempt 1 failed before any test ran, because the backend job could not pull its Postgres image
from public ECR. Attempt 2 re-ran only the failed jobs and passed. PR 12 moves that image to
`mirror.gcr.io` at the same digest, and its CI run 39324279613 passed on the mirror.

## Two things the record needed

- It carried no `pre_promotion_configuration` or `launch_configuration`, so the validator could not
  pass. They now state the owner's policy as given in this work: shadow at 10% with the evidence loop
  on before promotion, then `llm_primary` with the evidence loop on.
- `hashes.bundle` named the unreviewed 20260907 bundle (`65ba7fec...`). The evidence here uses the
  reviewed 20260928 bundle (`549af2ed...`, the one with the owner's report approval). I changed the
  hash to match. The owner should confirm that is the bundle to activate.

## llm_primary latency

The owner relaxed the `llm_primary` promotion gate in `docs/evaluation.md` from four seconds to
15 seconds on 2026-10-19.

| Configuration | Analyst p95 | Notes |
| --- | --- | --- |
| Shadow, evidence loop on (gate's configuration) | 1,026 ms | The load tool sends no `turn_id`, so no request reaches the model |
| `llm_primary`, evidence loop on | 10,500 ms | 20 turns, concurrency 10, p50 5,348 ms, 18 of 20 model-validated, 0 errors |

`warm_load` is marked passed for the first row, as the gate defines it. The second row meets the
relaxed 15-second gate. It is local, on one provider, with 20 turns; hosted latency still needs the
post-deploy load check.

## Still open

- Owner approvals: template, exceptions, report audit, evaluation labels, launch.
- Evaluation with and without services, 120 labels, ranked traces, 50-case semantic cohort.
- `shadow_evaluation`, `shadow_dependencies`, `production_router_contracts`.
- `active_archive_identity`, which must be read from production immediately before promotion.
- `rollback_snapshot` needs a restore rehearsal or a fresh database backup. A list of targets is not one.
- Production smoke, browser and load checks after deploy.

## Scope limits

The retrieval and load numbers come from a local restore with Qdrant and providers off. They say
nothing about hosted latency or Qdrant Cloud inference. The CI-bound checks record that the suites
passed, not each assertion. The accessibility check covers fixture surfaces, not the served site.
