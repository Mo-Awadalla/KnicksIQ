# Frozen evaluation contract, 2026-10-21

`expectations.json` is the frozen 120-case contract, SHA-256
`8da8be9d68a7111919d1e8d0d18d22da8bf8d3a7da34a7fe4688117cc37119f9`. It was built from the
owner-approved [adjudications](../evaluation-contract-20261019/adjudications-draft.json) with:

```
uv run --offline --frozen --package knicksiq-api python tools/release/build_eval_contract.py \
  --adjudications docs/release-evidence/evaluation-contract-20261019/adjudications-draft.json \
  --output docs/release-evidence/evaluation-contract-20261021/expectations.json
```

A rebuild reproduces the same bytes. `app.evaluation.release_runner.load_contract` accepts it
together with [the approval](evaluation-approval.json), whose `expectations_sha256` equals
the hash above.

| Property | Value |
| --- | --- |
| Questions | 120 original, `questions.jsonl` SHA-256 `a546b99c…ffdf482` |
| Semantic members | the fixed 50 |
| Dispositions | 65 answer, 46 clarify, 9 refuse |
| Context-free clarification | `aliases_typos-003` |
| Recall | k = max(5, target count), uncapped targets, ceiling 1.0, gate 0.95 |

[`owner-decisions.json`](owner-decisions.json) records the three scoped owner approvals of the
adjudications, the separate 20-question launch set, and the report template, correction
exception and audit. The contract approval and these decisions do not approve a quality
result, production mapping, hosted acceptance, the release record, deployment, alias
promotion or a budget change.
