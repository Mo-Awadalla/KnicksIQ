# Evaluation expectations contract, 2026-10-19

`tools/release/build_eval_contract.py` turns the agent-reviewed label package
(`evaluation-label-review-20260907/labels.jsonl`) into the 120-case contract that
`app.evaluation.release_runner` scores against. No question, category or disposition is changed.

`expectations.json` is a **draft**, SHA-256 `83cd9e7d58d056fba8b4953b0f1c53b790aaab403a4f2ff18dbc6836269536b9`.
The builder is deterministic. Rebuilding gives the same hash.

| Disposition | Cases |
| --- | ---: |
| answer | 58 |
| clarify | 53 |
| refuse | 9 |

50 cases are semantic members and count toward Recall@5.

## Why it is a draft

Five semantic members have no retrieval target in the proposals. Each is a clarification, because the
question has no single answer to retrieve:

| Case | Question |
| --- | --- |
| `turning_points-005` | How did the Knicks erase their largest deficit? |
| `turning_points-007` | What was the most damaging opponent run this season? |
| `aliases_typos-003` | How did JB play in that game? |
| `aliases_typos-005` | What was the Knics biggest run? |
| `aliases_typos-010` | What was NY's worst collpase? |

The runner requires a target for every semantic member, and the release gate requires all 50. The
builder does not invent targets. I checked the runner's `validate_contract` both ways. The draft is
refused. A copy where only these five get throwaway targets is accepted, so nothing else blocks
freezing.

## What the owner decides

1. **The five targets.** Write `adjudications.json`, mapping each case id to
   `{"semantic_targets": [...canonical ids...], "decision_basis": "..."}`. For the run questions, one
   option is every game whose report names the run. For "that game", no target exists without
   context. Changing semantic membership instead would shrink the fixed cohort, which the gate forbids.
2. **Freeze.** Run the builder with `--adjudications adjudications.json`. Status becomes `frozen`.
3. **Approve the 120 expectations.** Write an approval file with `owner`, `approved_at` and
   `expectations_sha256` equal to the frozen file's hash. That is the step the agent-reviewed labels
   have always waited for.
4. **Point the record at it.** The release validator requires `hashes.evaluation` to equal the frozen
   contract's hash. Today it holds the label file's hash.

## What then runs

- `--mode disabled` collects with Qdrant, Redis and the provider off. It needs no spend.
- `--mode primary` and `--mode shadow` need a counted provider wrapper. The runner refuses to call the
  provider without one, by design.
- Each answer then needs a review: assertion spans, fact ids and citations, per
  `docs/release/evaluation-review.md`. Scoring runs offline from those reviews.
