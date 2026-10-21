# Official evaluation, 2026-10-21

Tested commit `ab6b18014c7537384de29b3d1060081ccf5ffd33`; dataset `2025-26.20260928.1`; frozen,
owner-approved contract `8da8be9d…` (120 cases, the fixed 50 semantic members). Launch
configuration from `render.yaml`: `llm_primary`, evidence loop, Qdrant cloud inference, hybrid
retrieval and the LLM planner on; reranker and archive source units off; unpinned OpenRouter
routing with `deepseek/deepseek-v4.1-flash`.

**Result: both modes fail the release thresholds.** This is a scored evaluation, not a release
pass, and it does not approve anything.

| Metric | Gate | Primary | Service-disabled |
| --- | --- | --- | --- |
| Semantic Recall@k | ≥ 0.95 | 0.178 | n/a |
| Exact numeric correctness | 1.0 | 0.692 | 0.846 |
| Canonical entity correctness | 1.0 | 0.692 | 0.846 |
| Citation correctness | ≥ 0.95 | 0.692 | 0.846 |
| Paraphrase success | ≥ 0.95 | 0.692 | 0.846 |
| Correct abstention | 1.0 | 0.527 | 0.527 |
| Correct refusal | — | 1.0 | 1.0 |
| Invalid or unresolved reviews (`missing_labels`) | 0 | 44 | 33 |
| Missing ranked traces | 0 | 1 | — |

## Failure causes

| Cause | Cases | Modes |
| --- | --- | --- |
| Clarifications name candidate games (dates, opponents, scores) but attach no citations, so those factual statements cannot be supported | 25 | both |
| Follow-up clarifications ask "which game?" without naming any candidate from the conversation; Recall@k 0 | 10 | both |
| Wrong disposition: `turning_points-001/005/007`, `aliases_typos-005/010` clarify instead of answering; `single_game_narrative-006` answers instead of clarifying | 6 | both |
| Uncited "player rows are missing for N games" caveats that present non-appearances in a complete archive as data gaps | 8 | primary |
| `date_range_last_n-006` reports a wins-filtered population as all December road games (5 of 5, Dec 9–29; actually 5 of 8, Dec 2–31) | 1 | both |
| `single_game_narrative-020` swaps home/away when attributing leads in two Boston runs | 1 | primary |
| Other unsupported or uncited claims: `aliases_typos-008/009`, `date_range_last_n-012`, `single_game_narrative-015`, `turning_points-006` | 4–5 | mostly primary |
| `single_game_narrative-015` answered with an empty retrieval trace | 1 | primary |

Primary and disabled dispositions are identical, so routing, not the model, decides the six
mismatches. Paid collection: 120 counted calls, all settled within their verified bounds,
$0.107277 under the unchanged $2 cutoff. Two earlier attempts stopped on collector defects that
were then fixed (#32, #33); see `collection-summary.json`.

## Files

- `metrics-{primary,disabled}.json`: scorer output; binds the contract, approval, observations,
  reviews, mapping and runner by SHA-256.
- `reviews-{primary,disabled}.json`: per-case span reviews by six agent reviewers. Each recomputed
  facts from the approved bundle or the restored database. Unresolvable factual statements are
  kept and marked `unresolved`, never relabeled.
- `runtime-mapping.json`: runtime evidence IDs to canonical sources, built by
  `tools/release/build_runtime_mapping.py`. Calculations map to the rows they computed from;
  player identity units map to nothing.
- `collection-summary.json`: collection identities, spend, ledger and earlier attempts.

Observations contain opaque session tokens and stay private; their SHA-256 values are bound in
the metrics files.

## Reproduce

```sh
DB_URL=... uv run --package knicksiq-api python tools/release/build_runtime_mapping.py \
  --observations disabled.json primary.json --archive-units archive_units.jsonl --output mapping.json
uv run --package knicksiq-api python tools/release/evaluation_review_kit.py check \
  --contract expectations.json --observations primary.json --mapping mapping.json --reviews reviews-primary.json
cd apps/api && uv run --package knicksiq-api python -m app.evaluation.release_runner expectations.json \
  --approval evaluation-approval.json --mode primary --observations primary.json \
  --reviews reviews-primary.json --mapping mapping.json --output metrics.json
```

Scoring makes no provider calls.
