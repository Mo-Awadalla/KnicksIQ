# Evaluation expectations contract, 2026-10-19

`tools/release/build_eval_contract.py` turns the agent-reviewed label package
(`evaluation-label-review-20260907/labels.jsonl`) into the 120-case contract that
`app.evaluation.release_runner` scores against. No question, category or disposition is changed.

`expectations.json` is a **draft**, SHA-256 `e73f22f64b609189ba42a02a2aec9db5e3181cf5edd588c4b4f17fa9286d9b32`.
The builder is deterministic. Rebuilding gives the same hash.

| Disposition | Cases |
| --- | ---: |
| answer | 58 |
| clarify | 53 |
| refuse | 9 |

50 cases are semantic members and count toward Recall@5.

## Why it is a draft

Twelve semantic cases block freezing.

**Five have no retrieval target.** Each expects a clarification, so the proposals name nothing to
retrieve: `turning_points-005`, `turning_points-007`, `aliases_typos-003`, `aliases_typos-005`,
`aliases_typos-010`.

**Seven have targets the gate cannot reward.** Recall@5 for one case is at most 5 divided by its
target count. Six cases list 9 games and one lists 6, so they cap at 0.56 and 0.83. The best possible
mean over all 50 cases is 0.943, below the 0.95 gate, even with perfect retrieval and full marks on
the five open cases. These lists are source populations (for example every game against one
opponent). The September evaluation contract says not to treat a source population as relevant
top-5 targets and that no threshold is reduced. The builder now computes this ceiling and refuses
to freeze below the gate.

An earlier version of this README said only the five open cases blocked freezing. That was wrong.
I checked it with the runner's `validate_contract`, which does not compute the ceiling.

## What the owner decides

1. **Reviewed targets for the twelve.** For each, the five or fewer documents a correct answer would
   retrieve. A context-free question such as "How did JB play in that game?" has no such set, and
   every Brunson game would cap it near zero. That case needs an owner ruling, not a list.
2. **Freeze.** Write `adjudications.json` (case id to `{"semantic_targets": [...],
   "decision_basis": "..."}`) and run the builder with `--adjudications`. It freezes only when nothing is
   unresolved and the ceiling reaches 0.95.
3. **Approve.** An approval file with `owner`, `approved_at` and `expectations_sha256` equal to the
   frozen hash.
4. **Point the record at it.** Set `hashes.evaluation` to the frozen hash.

## What then runs

- `--mode disabled` collects with Qdrant, Redis and the provider off. It needs no spend.
- `--mode primary` and `--mode shadow` need a counted provider wrapper. The runner refuses to call the
  provider without one, by design.
- Each answer then needs a review: assertion spans, fact ids and citations, per
  `docs/release/evaluation-review.md`. Scoring runs offline from those reviews.
