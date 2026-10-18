# Evaluation approval package — owner pending

Candidate: `e003db2d7f179c8d490d90155f260ec0eeb31620`. The original 120 questions and labels are unchanged.

- Labels: `docs/release-evidence/evaluation-label-review-20260907/labels.jsonl`
- Label SHA-256: `7c3c549e6a540f4ce03a3fa4ba38821ddc6f7641c9d081270cff8607ec9b007e`
- [All 120 questions, canonical facts and decisions](../evaluation-label-review-20260907/review.md)
- [Hash-bound package and explicit adjudications](evaluation-approval-package.json)
- [Fresh source/content binding](content-binding.json): all 4,160 canonical references match the approved bundle; canonical hash `b2ad21c69175600c3192ef6133f8c11fd63890609a8204f92508a5fb04d05170`.

Proposed dispositions: **58 answers, 53 clarifications, 9 refusals**. Category counts remain 25 exact statistics, 15 date/last-N, 15 comparisons, 20 single-game narrative, 10 turning points, 10 follow-ups, 10 aliases/typos, 15 unsupported. No case is removed or rewritten to improve scores.

Approval covers the proposed dispositions, canonical facts, metric definitions and denominators: whole archived season including postseason unless restricted; player averages and last-N windows use played appearances; All-Star boundary is after February 15, 2026. Examples requiring explicit adjudication include which definition of back-to-back wins is intended, which two of four Boston games are meant, and causal “decisive” sequences unsupported by descriptive scoreboard facts. Missing follow-up context requires clarification, not automatic refusal. The JSON package lists every original/proposed disagreement.

This is content approval, not approval of execution metrics. Target content version is `2025-26.20260928.1`; seven original canonical collections match the label baseline exactly. The release bundle also contains 70 derived stat facts produced by the existing bundle builder; those were reproduced separately. Report approval has not granted evaluation approval.

## Proposed scoring decisions for review

1. Score all 120 cases. Preserve original questions/categories and record both original expectations and owner-adjudicated disposition. A clarification and a refusal are different outcomes; neither can stand in for the other.
2. Check typed facts, scope, denominator and canonical entity identity. Counts/scores must be exact. A displayed decimal must equal the canonical value rounded to its displayed precision, with the metric/unit stated. Do not learn acceptable prose or rounding from the candidate's answers. Exact wording is unnecessary only when the same independently defined fact is demonstrably expressed.
3. Map canonical NBA IDs to candidate release/database/vector IDs using independently verified metadata, retaining a local mapping artifact. Check each cited claim against that mapping and evidence content; matching a number alone is insufficient.
4. Preserve the original semantic evaluation scope. Capture ranked top-5/top-20 traces. Where an original semantic question is ambiguous and has no uniquely adjudicated target, mark its retrieval label unresolved. Do not omit it, turn it into a passing abstention, or report Recall@5 on a smaller replacement set. Additional contextualized tests must be separate from the fixed set and cannot silently replace it.
5. Reuse this rubric with Qdrant enabled and with Qdrant/Redis/OpenRouter disabled. Gates: numeric/entity correctness and correct abstention 100%; citation/paraphrase >=95%; enabled semantic Recall@5 >=95%; all 120 reviewed labels and zero missing ranked traces.

The pinned harness currently consumes original top-level labels rather than nested proposals, uses phrase matching, and treats every `answerable=false` as refusal. Passing this proposal JSON directly to it would mis-score cases. Before release metrics can pass, prepare and independently verify a local evaluation adapter or explicit per-case review protocol implementing the approved rubric and canonical/runtime mapping. Keep application source/candidate fixed. Unresolved semantic targets need owner adjudication; do not lower the gate or claim a pass.

Approval wording: “Approve the unchanged label batch `7c3c549e…b007e`, its explicit proposed dispositions/facts, and the scoring decisions in this package.” Any rejected case should be identified by its stable ID. Store the eventual approval separately with full artifact hashes; do not rewrite the original label file or its pending flags to manufacture approval. This approval would not authorize provider spend, staging, deployment or activation.
