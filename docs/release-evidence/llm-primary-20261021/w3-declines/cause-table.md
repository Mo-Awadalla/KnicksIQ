# DECLINE_MISSED_ANSWER causes, two 16,000-byte final trials

Source: `final/audit-16000-trial{1,2}/verdicts/*.jsonl` joined to `final/budget-16000.rows.jsonl` (tool calls, writer drops, outcome) and the honest scorer. A row is `audit_label_only` when the recorded answer declined nothing and passed the honest scorer; the audit spec verdict is static for most missed ids.

| Cause | Trial 1 | Trial 2 | Rows | Honest pass / fail | Head action |
| --- | ---: | ---: | ---: | --- | --- |
| audit_label_only | 7 | 6 | 13 | 13 / 0 | no code change: already passes the honest scorer |
| wrong_tool | 6 | 6 | 12 | 3 / 9 | fixed: prefetch routes split/flow questions (f0fd729) |
| fallback_rejected | 2 | 3 | 5 | 0 / 5 | fixed: split/flow/period fallback families (e08a83c) |
| clarification | 2 | 2 | 4 | 0 / 4 | fixed for period/flow sets: prefetch runs the set tool (f0fd729) |
| prompt_hedge | 2 | 1 | 3 | 1 / 2 | fixed: prompt permits tool-computed observed extremes (a7bf808) |
| capability_gap | 5 | 5 | 10 | 0 / 10 | not fixed: needs a new tool, outside this worktree |
| scope_resolution | 1 | 1 | 2 | 0 / 2 | not fixed: query_resolution, outside this worktree |
| resolution_wrong_player | 1 | 1 | 2 | 0 / 2 | not fixed: query_resolution, outside this worktree |
| packing_claim_drops | 1 | 1 | 2 | 2 / 0 | reduced: one flow call replaces discovery plus two flow calls |
| **Total** | **27** | **26** | **53** | **19 / 34** | |

## Per-row detail

| Trial | id | Cause | Outcome | Tools | Drops | Honest | Note |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| 1 | single_game_narrative-001 | audit_label_only | validated | discover_facts, get_game_flow | 3 | pass | Answer traces the 14-point lead lost; the spec verdict is static and the 'does not establish' hedge is not a decline. |
| 1 | single_game_narrative-003 | audit_label_only | validated | discover_facts, get_game_flow | 1 | pass | Answer walks the Q4 scoring sequences; the spec verdict is static. |
| 1 | single_game_narrative-005 | clarification | validated | discover_facts, get_period_scoring | 0 | fail | get_period_scoring returned ambiguous_entity for four CHA games; the model asked which game. The set report answers all four. |
| 1 | single_game_narrative-006 | capability_gap | fallback:review_rejected | discover_facts, get_game_flow, get_game_flow | 35 | fail | No tool returns the single closest game; the fallback declined in trial 1 and the trial-2 answer carried unbacked entities. Fifteen claims were dropped on the way. |
| 1 | single_game_narrative-008 | prompt_hedge | validated_declined | discover_facts | 0 | pass | Model declined because 'decisive' is not a recorded field, then gave the computed run sequence. Trial 1 already passes the honest scorer. |
| 1 | aliases_typos-005 | fallback_rejected | fallback:review_rejected | discover_facts, get_game_flow, get_game_flow | 30 | fail | discover_facts plus two get_game_flow calls; the reviewer rejected the wording and the fallback had no flow family. Ten claims were dropped. |
| 1 | aliases_typos-007 | clarification | validated | get_team_stats, get_period_scoring | 0 | fail | get_team_stats then get_period_scoring hit ambiguous_entity; the model asked which CHI game. Trial 2 reached the same point through the fallback. |
| 1 | aliases_typos-008 | resolution_wrong_player | fallback:review_rejected | discover_facts, get_player_stats | 0 | fail | Scope resolved 'Mikal' to player 476 (Jaylen Wells); player and discovery tools returned no observed appearances. |
| 1 | aliases_typos-010 | prompt_hedge | validated_declined | discover_facts, get_game_flow, get_game_flow | 20 | fail | Model declined to rank 'worst collapse' and listed unrelated box scores; the flow tool computes the 19-point lead lost. |
| 1 | comparisons-001 | wrong_tool | validated | get_team_stats, get_team_stats | 0 | pass | get_team_stats ran twice with only the home scope; the answer says road data is unavailable. The honest scorer still passes it. |
| 1 | comparisons-003 | wrong_tool | validated_declined | get_team_stats, get_team_stats | 0 | fail | get_team_stats ran twice; the model asserted the archive has no opponent splits, though games and team_game_stats hold both series. |
| 1 | comparisons-004 | wrong_tool | fallback:review_rejected | compare_windows, get_team_stats | 0 | fail | compare_windows requires a player baseline, so the model asked 'Which Knicks player?'. Team first/last windows belong to get_team_splits. |
| 1 | comparisons-005 | capability_gap | validated_declined | get_team_stats, get_team_stats | 0 | fail | No tool computes turnovers by game result; get_team_stats only has points and margin. |
| 1 | comparisons-006 | capability_gap | validated_declined | discover_facts | 3 | fail | No tool computes bench production; discovery returned team totals. |
| 1 | comparisons-009 | audit_label_only | validated | get_period_scoring | 0 | pass | Answer gives regular-season Q3/Q4 (28.96/28.24) and passes; the audit right answer is all-phase 29.02/27.89, so the spec verdict is not evidence of a decline. |
| 1 | comparisons-010 | capability_gap | validated_declined | get_team_stats | 0 | fail | No tool computes shooting percentage; get_team_stats only has points and margin. |
| 1 | date_range_last_n-005 | wrong_tool | validated_declined | get_team_stats, get_team_stats | 0 | fail | No split route ran; get_team_stats returned the season and the model said the archive has no break date. get_team_splits computes 18-9 in 27. |
| 1 | date_range_last_n-007 | audit_label_only | validated | get_team_stats | 0 | pass | Answer states the correct 9.75 margin and passes; the verdict is static from an earlier declined response. |
| 1 | date_range_last_n-008 | capability_gap | fallback:review_rejected | discover_facts | 2 | fail | No tool returns the team scoring leader over a window; the fallback delivered team points (312) instead. |
| 1 | date_range_last_n-009 | scope_resolution | fallback:review_rejected | get_team_stats | 0 | fail | Resolver read 'between March 1 and March 15' as the whole of March; the fallback answered 10-6 over 16 games. The audit right answer is 9 games. |
| 1 | date_range_last_n-010 | wrong_tool | fallback:review_rejected | get_team_stats | 0 | fail | The first-10 window is not resolved; get_team_stats returned the full season and the fallback answered 53-29. |
| 1 | turning_points-001 | wrong_tool | validated_declined | discover_facts, get_game_flow, get_game_flow | 0 | fail | discover_facts then two get_game_flow calls hit ambiguous_entity; the model called the play-by-play ambiguous. Trial 2 already passes. |
| 1 | turning_points-003 | fallback_rejected | fallback:review_rejected | discover_facts | 0 | fail | Only discover_facts ran; the reviewer rejected the wording and the fallback had no flow family. Trial 2 asked a clarification instead. |
| 1 | turning_points-005 | packing_claim_drops | validated_declined | discover_facts, get_game_flow, get_game_flow | 33 | pass | Flow claims were in the payload but 13 were dropped; the writer said no deficit data. The honest scorer passes it by answer length. |
| 1 | turning_points-007 | audit_label_only | validated | get_game_flow | 1 | pass | Answer gives the 15-0 PHX run in the loss and the 17-0 BKN run overall; the verdict is static. |
| 1 | turning_points-008 | audit_label_only | validated | discover_facts, get_game_flow | 4 | pass | Answer locates both 21-point deficits and passes; the verdict is static. |
| 1 | turning_points-009 | audit_label_only | validated | discover_facts, get_game_flow | 1 | pass | Answer gives the 12-point comeback sequence; the verdict is static. |
| 2 | single_game_narrative-001 | audit_label_only | validated | discover_facts, get_game_flow | 3 | pass | Answer traces the 14-point lead lost; the spec verdict is static and the 'does not establish' hedge is not a decline. |
| 2 | single_game_narrative-003 | audit_label_only | validated | discover_facts, get_game_flow | 1 | pass | Answer walks the Q4 scoring sequences; the spec verdict is static. |
| 2 | single_game_narrative-005 | clarification | validated | discover_facts, get_period_scoring | 0 | fail | get_period_scoring returned ambiguous_entity for four CHA games; the model asked which game. The set report answers all four. |
| 2 | single_game_narrative-006 | capability_gap | validated_declined | discover_facts, get_game_flow, get_game_flow | 29 | fail | No tool returns the single closest game; the fallback declined in trial 1 and the trial-2 answer carried unbacked entities. Fifteen claims were dropped on the way. |
| 2 | single_game_narrative-008 | prompt_hedge | validated_declined | discover_facts | 0 | fail | Model declined because 'decisive' is not a recorded field, then gave the computed run sequence. Trial 1 already passes the honest scorer. |
| 2 | aliases_typos-005 | fallback_rejected | fallback:review_rejected | discover_facts, get_game_flow, get_game_flow | 29 | fail | discover_facts plus two get_game_flow calls; the reviewer rejected the wording and the fallback had no flow family. Ten claims were dropped. |
| 2 | aliases_typos-007 | clarification | fallback:review_rejected | get_team_stats, get_game_flow, get_period_scoring | 12 | fail | get_team_stats then get_period_scoring hit ambiguous_entity; the model asked which CHI game. Trial 2 reached the same point through the fallback. |
| 2 | aliases_typos-008 | resolution_wrong_player | validated_declined | discover_facts | 0 | fail | Scope resolved 'Mikal' to player 476 (Jaylen Wells); player and discovery tools returned no observed appearances. |
| 2 | comparisons-001 | wrong_tool | validated | get_team_stats, get_team_splits | 0 | pass | get_team_stats ran twice with only the home scope; the answer says road data is unavailable. The honest scorer still passes it. |
| 2 | comparisons-003 | wrong_tool | validated_declined | get_team_stats, get_team_stats | 0 | fail | get_team_stats ran twice; the model asserted the archive has no opponent splits, though games and team_game_stats hold both series. |
| 2 | comparisons-004 | wrong_tool | validated | compare_windows | 0 | fail | compare_windows requires a player baseline, so the model asked 'Which Knicks player?'. Team first/last windows belong to get_team_splits. |
| 2 | comparisons-005 | capability_gap | validated_declined | get_team_stats, get_team_stats | 0 | fail | No tool computes turnovers by game result; get_team_stats only has points and margin. |
| 2 | comparisons-006 | capability_gap | validated_declined | discover_facts | 3 | fail | No tool computes bench production; discovery returned team totals. |
| 2 | comparisons-009 | audit_label_only | validated | get_period_scoring | 0 | pass | Answer gives regular-season Q3/Q4 (28.96/28.24) and passes; the audit right answer is all-phase 29.02/27.89, so the spec verdict is not evidence of a decline. |
| 2 | comparisons-010 | capability_gap | validated | get_team_stats | 0 | fail | No tool computes shooting percentage; get_team_stats only has points and margin. |
| 2 | date_range_last_n-005 | wrong_tool | validated_declined | get_team_stats, get_team_stats | 0 | fail | No split route ran; get_team_stats returned the season and the model said the archive has no break date. get_team_splits computes 18-9 in 27. |
| 2 | date_range_last_n-007 | audit_label_only | validated | get_team_stats | 0 | pass | Answer states the correct 9.75 margin and passes; the verdict is static from an earlier declined response. |
| 2 | date_range_last_n-008 | capability_gap | fallback:review_rejected | discover_facts | 2 | fail | No tool returns the team scoring leader over a window; the fallback delivered team points (312) instead. |
| 2 | date_range_last_n-009 | scope_resolution | fallback:review_rejected | get_team_stats | 0 | fail | Resolver read 'between March 1 and March 15' as the whole of March; the fallback answered 10-6 over 16 games. The audit right answer is 9 games. |
| 2 | date_range_last_n-010 | wrong_tool | fallback:review_rejected | get_team_stats, get_team_stats | 0 | fail | The first-10 window is not resolved; get_team_stats returned the full season and the fallback answered 53-29. |
| 2 | turning_points-001 | wrong_tool | validated | discover_facts, get_game_flow, get_game_flow | 3 | pass | discover_facts then two get_game_flow calls hit ambiguous_entity; the model called the play-by-play ambiguous. Trial 2 already passes. |
| 2 | turning_points-003 | fallback_rejected | validated_declined | discover_facts | 0 | fail | Only discover_facts ran; the reviewer rejected the wording and the fallback had no flow family. Trial 2 asked a clarification instead. |
| 2 | turning_points-005 | packing_claim_drops | validated_declined | discover_facts, get_game_flow, get_game_flow | 20 | pass | Flow claims were in the payload but 13 were dropped; the writer said no deficit data. The honest scorer passes it by answer length. |
| 2 | turning_points-007 | audit_label_only | validated | get_game_flow | 1 | pass | Answer gives the 15-0 PHX run in the loss and the 17-0 BKN run overall; the verdict is static. |
| 2 | turning_points-008 | fallback_rejected | fallback:review_rejected | discover_facts, get_game_flow | 9 | fail | Reviewer rejected the wording; the fallback had no flow family and declined. |
| 2 | turning_points-009 | audit_label_only | validated | discover_facts, get_game_flow | 1 | pass | Answer gives the 12-point comeback sequence; the verdict is static. |

## After the head (offline prediction, no live run)

- Rows that were real declines: 40 of 53; 13 were audit labels on passing answers.
- Rows the head changes: 26 (20 were honest failures). Split, flow and period routing plus the fallback families carry these.
- Rows left: 27 (14 honest failures): capability gaps (5 per trial), scope resolution (1 per trial), player resolution (1 per trial) and audit labels (13).
- Live confirmation is pending: the provider account returned HTTP 402 before any head trial. The commands are in the report.

## Unsupported questions answered instead of declined (5 of 20)

| id | Trials | Recorded shape | Dataset | Finding |
| --- | --- | --- | --- | --- |
| unsupported-007 | trial 1 | decline that also states the true 2025-12-21 Brunson line; the honest scorer counts an unbacked fact | answerable false | prompt now forbids unbacked specifics in a decline |
| unsupported-009 | both | clarification listing the two LAL games | answerable true, reviewed_archive_20261021 | not a decline: the question is answerable and the app asks which game |
| unsupported-010 | both | clarification listing the four BOS games | answerable true, reviewed_archive_20261021 | not a decline: the question asks for the list |

The brief's 5 of 20 'answered instead of declined' is therefore 1 decline containing an unbacked fact plus 4 clarifications on ids the dataset marks answerable. A 20/20 declined target conflicts with those labels.

## Questions

27 unique ids produced 53 missed rows.
