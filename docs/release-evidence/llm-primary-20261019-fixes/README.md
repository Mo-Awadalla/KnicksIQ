# Fixes for the two confirmed llm_primary failure classes, 2026-10-19

Follows `docs/release-evidence/llm-primary-20261019`. Same harness, same 110 non-follow-up
questions, same release, `deepseek/deepseek-v4.1-flash` pinned to DeepInfra fp8, `json_object`
(today's production format). Two repeats per arm. The baseline is arm A from the earlier directory.

## Arms

- **A** is main before these commits.
- **S** adds slot-local indexes. The model numbers each required slot's choices from 0 and the
  decoder maps them back. Before, slot 1 needed shared-table ordinals 5 to 9.
- **E** adds S plus one input change. A writer turn whose claims the backend fixes no longer fills
  the input cap with receipts that no claim cites.

## Staged counts

| What the turn demonstrably did | A r1 | A r2 | S r1 | S r2 | E r1 | E r2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Reached the model | 61 | 61 | 61 | 61 | 61 | 61 |
| Reviewer reached | 29 | 33 | 46 | 44 | 55 | 55 |
| Reviewer accepted | 24 | 29 | 42 | 41 | 47 | 47 |

The target set before the work was at least 50 reached and 45 accepted. E meets it in both repeats.
"Reviewer accepted" counts `llm_validated`, which includes validated refusals. I read eleven E
answers by hand. The record, points, average, home, road and loss answers match the archive
(69-32, 11,750, 116.34, 37, 32, 32).

## Why each change

1. **Selection.** Sealed-choice rejections fall from 12 or 13 per run to 1 per run. All 38 earlier
   failures were two-slot record questions where the model wrote small indexes. A model that counts
   each slot from 0 now decodes correctly, with or without a provider schema.
2. **Reviewer-input overflow.** In A, overflow turns cited an average of 4.9 game receipts against
   0.5 in validated turns. Those receipts were filler. The writer input listed up to nine unsupporting
   game or lexical receipts because evidence was packed greedily, so the writer cited them and the
   reviewer's input could not hold them. Overflows fall from 14 to 17 per run to 2 and 4 in E.

## What remains

Six or seven of 61 model turns still end before the reviewer in E.

- 2 to 4 overflows, all on `comparisons-002` ("Compare Brunson and Towns") and one other.
- One sealed-choice failure on `single_game_narrative-011`. Its four-slot wire has a last slot with
  one choice, and the model answered `{"0": 0, "1": 1, "2": 2, "3": 3}`. It used the slot number as
  the index again.
- One selection of the same claim twice (`comparisons-011`), unchanged from A.
- One or two provider timeouts.

Reviewer rejections rise from 3 per run in S to 7 and 9 in E, because E sends more turns to the
reviewer. I did not investigate them.

## Caveats

- Counts move by a few between repeats even at temperature 0.
- Two repeats on one provider and one model. Production routing used four providers in an earlier run
  and did not change the result for A.
- E also changes what evidence reaches the writer for claim-complete questions. Narrative questions
  without required slots are unchanged. The full backend suite passes (1254 tests).
- The harness's "met expectation" number mislabeled answers containing "which" as clarifications. The
  detector now requires a question mark, and the reducer no longer reports that row.
