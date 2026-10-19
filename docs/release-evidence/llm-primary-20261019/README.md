# llm_primary live E2E on main, 2026-10-19

`tools/release/analyst_live_e2e.py` sends benchmark questions through the in-process API with the
real DeepSeek provider against a locally restored `2025-26.20260928.1` release. Qdrant is off.
It records every model call, the raw reply, the serving provider, request sizes and the exact
exception. `tools/release/analyst_failure_report.py` reduces the response files to the tables below.

## Setup of the controlled run

- Code: `14e5f11` plus the ledger fix in this PR. Model `deepseek/deepseek-v4.1-flash`.
- Questions: all 110 non-follow-up benchmark questions, not only earlier failures. 61 reach the
  model. The other 49 get a deterministic backend answer, refusal or clarification.
- Provider pinned to DeepInfra fp8 (`OPENROUTER_PROVIDER_ROUTE`) for every arm except `A_prod`,
  which uses the production routing. `A_prod` was served by DeepInfra (81 calls), Makora (9),
  BaseTen (3) and Together (1).
- Arm A is `json_object`, today's behavior. Arm B is `json_schema` on the same slot and ordinal
  format. Each arm ran twice, and `A_prod` once. Temperature is 0, yet counts still moved between
  repeats of the same arm.

## Staged counts

| What the turn demonstrably did | A r1 | A r2 | A prod | B r1 | B r2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reached the model | 61 | 61 | 61 | 61 | 61 |
| Writer reply received | 61 | 61 | 61 | 61 | 61 |
| Reviewer reached | 29 | 33 | 31 | 53 | 54 |
| Reviewer accepted | 24 | 29 | 28 | 20 | 27 |
| Met expectation (all 110) | 33 | 38 | 37 | 29 | 35 |

"Reviewer reached" means the writer reply decoded and passed structural validation, then a review
call was made. It is read from the recorded calls, not from the outcome label.
`met expectation` still depends on a phrase match and on unreviewed draft labels.

## Where each turn ended before review, by first failure

| Cause | A r1 | A r2 | A prod | B r1 | B r2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sealed claim choice rejected (two-slot record questions) | 13 | 12 | 13 | 0 | 0 |
| A sealed claim selected twice | 1 | 1 | 1 | 1 | 1 |
| Reviewer input too large, after a valid writer answer | 17 | 15 | 15 | 7 | 6 |

## What is established

1. **The sealed-choice failure has one shape.** All 38 failures across the three `json_object`
   runs are two-slot record questions, "wins and losses", where slot 1 accepts ordinals 5 to 9.
   In the one run I decoded in full (A r1), 12 of 13 replies were `{"0": 0, "1": 1}` or
   `{"0": 1, "1": 0}` and one was `{"0": 0, "1": 0}`. Those are claim indexes where the protocol wants
   an offset ordinal. The same slot shape passes 0 or 1 of 13 under `json_object`, and 13 of 13
   under `json_schema`. One-slot questions pass 26 of 26 under `json_object`. The same questions fail
   identically in every `json_object` run, so this is not noise.
2. **A second failure class has nothing to do with ordinals.** The reviewer's input does not fit the
   8,000-byte cap. It always happens after one valid writer answer and before any review call. My
   first report counted these as claim-selection failures, because the harness inherited the
   previous stage label. `json_object` embeds the schema in the payload, about 900 bytes more than
   `json_schema`, which is why the count drops from 14 to 17 to 6 to 7.
3. **Schema enforcement fixes selection but not end-to-end acceptance.** B reaches the reviewer on
   53 or 54 turns against 29 to 33 for A. It accepts 20 and 27, against 24, 29 and 28 for A. Reviewer
   rejections rise from 4 to 6 per run to 27 and 33.
4. **Each required slot offers one claim.** Slots show 1 or 5 choices, and the five are
   precision variants of that one claim. The model's real decision is mostly precision.

## What is not established

- **Why B's reviewer rejects more.** In rejected B reviews the first factual assertion has empty
  support arrays in 33 of 33 cases. It also has them in 6 of 20 accepted B reviews, so empty arrays
  neither cause nor explain every rejection. Whether the schema changes the reviewer's behavior is
  unproven.
- **Arm C is invalid.** It kept the schema for the writer and dropped it for the reviewer. That removed
  the only copy of the review format from the request, so the one reviewer reply I read used a different JSON
  shape (`{"verdicts": [...]}`), and 52 turns were reviewer-rejected in each C run, against 27 to 33 in B. The arm cannot say
  anything about the schema's effect on review. Its summary files are kept as `C_writer_*`.
- **Whether slot-local ordinals or choice IDs would fix selection under `json_object`.** The
  evidence supports trying them, because the failure is confined to offset ordinals. It is untested.
- **The 20 non-record failures in the first 70-question run**, and whether the reviewer's input
  overflow depends on the question or on the provider.

## Decision input

Turning on `json_schema` alone is not a win, because it trades 13 selection failures for about 25
more reviewer rejections. A change that keeps `json_object` and removes the offset, for example
slot-local indexes or short per-slot IDs, would remove the confirmed selection failure without
touching the reviewer. It could add up to 13 reviewer-reached turns per 61. The overflow failures
need a separate fix.

## Earlier run on `14e5f11` (70 questions, one run)

Of 70 questions, 11 had a validated model answer, 21 ended before review, 25 got a backend
clarification, 8 a correct refusal, 3 a reviewer rejection and 2 other. The 21 turns that ended
before review were reported then as claim-selection failures. The controlled run shows they were a
mix of sealed-choice errors and reviewer-input overflows.

## Questions the backend answers with a clarification

25 of 70 get "Which archived BOS game date should I use". These are real ambiguities (four to nine
games against each opponent) and are a product choice, not a data or model failure.
