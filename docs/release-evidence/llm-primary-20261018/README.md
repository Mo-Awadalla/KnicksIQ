# llm_primary live E2E, 2026-10-18

`tools/release/analyst_live_e2e.py` sends benchmark questions through the in-process API with the
real DeepSeek provider against a restored `2025-26.20260928.1` release. Qdrant is off.

## Two metrics

- `validated` (files `baseline` to `after-fix4`) counts reviewer acceptance only. It rose from
  9/35 to 59/70, but it also counts "I can't give that" answers, so it overstates usefulness.
- `meets_expectation` (file `final3-n70` and its `.responses.jsonl`) also requires a substantive
  answer for answerable questions and a decline for unsupported ones. Decline detection is a
  phrase match and the expectations come from unreviewed draft labels. Treat it as a screen, then
  read the responses.

## Result of the last run (70 questions)

| Category | Meets expectation |
| --- | --- |
| exact_statistics | 9/10 |
| date_range_last_n | 9/10 |
| aliases_typos | 6/10 |
| unsupported | 5/10 |
| turning_points | 4/10 |
| comparisons | 2/10 |
| single_game_narrative | 2/10 |
| Total | 37/70 |

Statistics questions are answered. Comparisons, narratives and turning points mostly decline
because the analyst tools only calculate full-game totals. No tool covers home/road splits,
quarters or play-by-play.

## Fixes behind the series

1. A missing monthly budget ledger blocked every model call. It now starts at zero.
2. The model sent team metrics such as `wins` to tools that ignore `metric`, which aborted the turn.
3. The model copied the whole claim into `displayed_value`. The prompt and repair hint now say
   `value` only.
4. The reviewer's citations of claim-backed evidence were rejected. They are now accepted.
5. The reviewer mislabeled refusals as factual. The prompt now names coverage and conversational.
6. Off-schema or self-contradicting actions get one retry.
7. Claims carried about 100 game ids each, so only one or two of wins, losses, points and margin
   reached the model. The model view now omits server-side fields.
8. `get_team_stats` returns per-game points and margin when asked for an average.
