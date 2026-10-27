# Failure attribution: the 33 misses in the `llm_primary` E2E

Part of #38, ticket #40. Read-only analysis of:

- `docs/release-evidence/llm-primary-20261018/final3-n70.responses.jsonl` (the 70 rows)
- `docs/release-evidence/llm-primary-20261018/final3-n70.json` and `README.md`
- `apps/api/app/evaluation/questions.jsonl` (the benchmark `tools/release/analyst_live_e2e.py:29` sends)
- `apps/api/app/services/query_resolution.py`, `analyst_dispatch.py`, `analyst_tools.py`,
  `analyst_calculations.py`, `analyst_provider.py`, `analyst_loop.py`, `analyst_fallback.py`

No provider call and no database query was made. The scope regexes were evaluated statically on
the question text. Tool-call traces are not in the artifact, so anything about what the model
asked a tool is marked **[INFERENCE]**.

Two properties of the harness matter for every row below:

- `meets_expectation` only checks the outcome string: `validated` for `answerable: true`,
  `validated_declined` for `answerable: false` (`tools/release/analyst_live_e2e.py:81-85`). It
  does not check that an answerable answer is substantive, so a clarification-only answer is a
  pass.
- Every one of the 120 benchmark rows has `label_status: needs_archive_review` with empty
  `filters` and `required_facts` (`apps/api/app/evaluation/questions.jsonl`). "Answerable" is a
  draft label, not a reviewed expectation.

## Counts

| Primary cause | n | ids |
| --- | --- | --- |
| Scope-caused (regex collapse / override) | 3 | `comparisons-001`, `comparisons-006`, `comparisons-010` |
| Missing tool (quarter, halftime, play-by-play, runs, comparison primitive) | 16 | see below |
| Review/provider failure | 7 | `exact_statistics-009`, `date_range_last_n-007`, `comparisons-002`, `unsupported-006`, `unsupported-008`, `turning_points-003`, `aliases_typos-010` |
| Clarification-correct | 3 | `single_game_narrative-002`, `single_game_narrative-004`, `aliases_typos-008` |
| Label/scorer error | 4 | `unsupported-005`, `unsupported-009`, `unsupported-010`, `comparisons-007` |
| **Total** | **33** | |

Shares: tools 48%, review/provider 21%, scope 9%, label/scorer 12%, clarification 9%.
Scope is the smallest bucket. The two adjacent rows (`comparisons-003` and `comparisons-005`)
that a scope/compare schema would also touch are counted under missing tool because the decisive
gap is the comparison primitive, not the parser (details below).

## Scope-caused: 3

All three are comparisons, and all three are the collapse classes named in #38.

### `comparisons-001` — "Compare the Knicks' offense at home and on the road."

Response: *"the available evidence covers only Knicks home games (48 games in scope), with no
road-game data retrieved"* (`final3-n70.responses.jsonl`).

`home_away = "home" if re.search(r"\bhome\b", q) else "away" if ...` (`query_resolution.py:389-395`)
sees `home` first and never looks at `road`; candidates are then reduced to NYK home games
(`query_resolution.py:415-418`). The model cannot recover: `execute_call` resolves the call's own
question, then overwrites every truthy field with the user-scope value
(`analyst_dispatch.py:58-72`). A call whose `question` says "road" is reset to `home`.

### `comparisons-006` — "Was the bench more productive in home or away games?"

Response: *"The retrieved data covers only home games ... there is no away-game comparison set."*

Same mechanism: `home` at `query_resolution.py:389-395`, filter at `query_resolution.py:415-418`,
override at `analyst_dispatch.py:58-72`.

### `comparisons-010` — "Did the Knicks shoot better in wins or losses?"

Response: *"The archive here covers only Knicks wins (game_result = W), so there are no loss games
to compare shooting against."*

This is the wins/losses first-match. `is_record_request` exists to avoid it, but its exemption
`\b(?:only|in)\s+(?:wins?|loss(?:es)?)\b` matches the "in wins" in this question
(`query_resolution.py:142`), so `is_record_request` returns `False` (`query_resolution.py:139-147`)
and `game_result` becomes `W` (`query_resolution.py:396-404`). The win filter runs at
`query_resolution.py:423-432`; the override at `analyst_dispatch.py:58-72` re-imposes `W` on any
narrower call.

The override is not needed to explain the first miss — the up-front scope is already wrong — but
it is why a model call cannot repair it. That a call actually tried to widen is unobserved
**[INFERENCE]**.

### Adjacent, deliberately not counted as scope

- `comparisons-003` ("Boston or Toronto") resolves `opponent_id = team_ids[0] if len(team_ids) == 1
  else None` (`query_resolution.py:351`), so both opponents disappear. A multi-valued opponent
  field would help, but the answer still needs a team-level comparison; `compare_windows` calls
  `player()` for both windows (`analyst_dispatch.py:117-118`), so it cannot compare team
  populations. Counted as missing tool.
- `comparisons-005` ("wins and losses by average turnover count") is *not* collapsed: without
  "in wins" the record-request branch returns `None` (`query_resolution.py:139-147`). The failure
  is that `team()` has no turnover metric (`analyst_calculations.py:14-24`, `94-114`) and
  `compare_windows` is player-only. Counted as missing tool.

## Missing tool: 16

Each response is a correct explanation of a capability gap, not a wrong scope.

| id | Response evidence | Gap |
| --- | --- | --- |
| `comparisons-003` | "does not include Knicks results broken out by opponent Boston or Toronto" | No team-level grouped comparison; `compare_windows` calls `player()` (`analyst_dispatch.py:117-118`), and two teams leave `opponent_id=None` (`query_resolution.py:351`). |
| `comparisons-005` | "no loss count or average turnover figures for wins versus losses were returned" | `team()` emits wins, losses, points, margin only (`analyst_calculations.py:105-114`); no team turnovers; compare is player-only. |
| `comparisons-009` | "available calculations support full-game box scores only, so quarter-by-quarter splits aren't in the data I can query" | `_periods` returns `[3, 4]` (`query_resolution.py:250-264`); dispatch rejects any `periods` for non-archive tools (`analyst_dispatch.py:73-77`). |
| `single_game_narrative-001` | "doesn't contain play-by-play or lead-tracking data" | Archive exposes only game scores, player box scores and archive evidence (`analyst_tools.py:158-167`). |
| `single_game_narrative-003` | "only support full-game box scores, not quarter-by-quarter splits" | `periods=[4]` (`query_resolution.py:250-264`) then `analyst_dispatch.py:73-77`. |
| `single_game_narrative-005` | "doesn't include halftime splits" | `_periods` knows "first half"/"second half" only (`query_resolution.py:257-260`); "after halftime" parses to `[]`, and no period data exists anyway. |
| `single_game_narrative-006` | "no tool rounds remain to pull the game score or archive detail needed to identify the closest game" | No game-level margin ranking tool; `team()` returns one population aggregate (`analyst_calculations.py:105-114`). The round-budget symptom is **[INFERENCE]** from the text. |
| `single_game_narrative-008` | "doesn't contain possession-level data" | No possession/play-by-play data. |
| `single_game_narrative-010` | "doesn't contain a causal explanation ... Box scores do not establish causation" | Manifest known gap (`analyst_tools.py:164-167`); no causal/narrative tool. |
| `turning_points-001` | "doesn't include scoring-run (in-game run) tracking" | No in-game run data. |
| `turning_points-005` | "doesn't contain a play-by-play or deficit-tracking record" | No play-by-play/deficit data. |
| `turning_points-007` | "doesn't contain opponent-run data (scoring runs within games)" | No run data. |
| `turning_points-008` | "doesn't contain a play-by-play or lead-tracking record" | No play-by-play/lead data. |
| `turning_points-009` | "doesn't contain play-by-play sequence data" | No play-by-play data. |
| `aliases_typos-005` | "the archive has no play-by-play or scoring-run data" | No run data ("biggest run" is not a win-streak question; there is no streak question in the 120-row benchmark). |
| `aliases_typos-007` | "available evidence covers the full game, not a 4th-quarter split ... I don't have quarter-by-quarter data" | `_periods` does not parse "4Q" (`query_resolution.py:250-264`), so `periods=[]`; even with `[4]` the tool rejects splits (`analyst_dispatch.py:73-77`). |

`single_game_narrative-010`, `turning_points-007` and the run questions are additionally mislabeled
`answerable: true` in the draft benchmark, but the product gap is the missing tool, which is the
primary cause.

## Review/provider failure: 7

| id | Outcome | Evidence |
| --- | --- | --- |
| `exact_statistics-009` | `fallback:review_rejected` | Model wording rejected; fallback is the capped stat dump *"Knicks wins: 0 over 32 archived games. Knicks losses: 32 ... points: 3421"*. `render_fallback` keeps only the first three claims (`analyst_loop.py:301`), so margin is never shown. Underlying gap: only "biggest win" gets a game selector (`query_resolution.py:444-456`); there is no largest-loss selector. |
| `date_range_last_n-007` | `validated_declined` | Answer says *"no margin value"*, but `team()` emits `margin_per_game` (`analyst_calculations.py:107-112`). The answer cites exactly three claims (wins, losses, points_per_game). Claim payload construction silently skips a claim that does not fit the input budget (`analyst_provider.py:199-231`); the dropped claim is the fourth/last one, margin. Cause of the drop is **[INFERENCE]** from the claim order and the three cited claims; either way this is provider/reviewer, not scope. |
| `comparisons-002` | `fallback:review_rejected` | Substantive answer: *"Karl-Anthony Towns: 19.2 points ... Jalen Brunson: 26.5 points ..."*; rejected by evidence review. |
| `unsupported-006` | `fallback:review_rejected` | Fallback is a record dump plus a live-status sentence; the question should be declined. |
| `unsupported-008` | `fallback:review_rejected` | Fallback answers a next-season question with the 2025-26 average; the question should be declined. |
| `turning_points-003` | `failed:review:ValueError` | *"Model or budget unavailable."* Provider/stage failure. |
| `aliases_typos-010` | `failed:review:ValueError` | *"Model or budget unavailable."* Provider/stage failure. |

`exact_statistics-009` is the one row where "review failure" and "missing tool" compete. The
observed outcome is a review rejection of proposed wording that had no per-game claim to stand on;
the note records the underlying selector gap so the tool count is not read as smaller than it is.

## Clarification-correct: 3

These runs asked a legitimate disambiguation. The benchmark expects a substantive answer, so the
scorer marks them as misses; `single_game_narrative-002/-004` were additionally rejected by the
reviewer.

| id | Evidence | Mechanism |
| --- | --- | --- |
| `single_game_narrative-002` | *"Which subject did you mean? 2025-11-30: TOR at NYK; 2025-12-09: NYK at TOR; ..."* (5 games) | `descriptive_reference` plus `len(candidates) > 1` sets `ambiguous_game` and builds the date/team options (`query_resolution.py:505-510`). Outcome is `fallback:review_rejected` because the reviewer rejected the clarification wording. |
| `single_game_narrative-004` | *"Which subject did you mean? 2025-11-02: CHI at NYK; 2026-02-22: NYK at CHI; 2026-04-03: CHI at NYK"* | Same path. `game_result=W` from "win the Chicago game" narrows four CHI games to the three wins, so three options are offered. |
| `aliases_typos-008` | *"the five games in scope ... are ambiguous — I'd need you to pick one before I can pull his box score"* | The model asked; the resolver did not, because the question has no "game" noun and `descriptive_reference` stays false (`query_resolution.py:434-443`). The disambiguation is still legitimate (five TOR games, no delivered Mikal rows). |

## Label/scorer error: 4

| id | Evidence | Error |
| --- | --- | --- |
| `unsupported-005` | *"Possession-level data isn't available in this dataset, and the requested date (2099-01-01) falls outside the covered 2025-26 season."* | A correct decline, but the `DECLINE` phrase match (`tools/release/analyst_live_e2e.py:60-66`) does not match "isn't available" or "falls outside", so the outcome is `validated` instead of `validated_declined`. |
| `unsupported-009` | *"Which Lakers game do you mean: 2026-02-01 LAL at NYK, or 2026-03-08 NYK at LAL?"* | The archive has two Lakers games, so the question is answerable by disambiguation; the draft labels it `answerable: false` and expects a decline phrase, which a clarification does not contain. Resolver's `ambiguous_game` path (`query_resolution.py:505-510`) supplied the options. |
| `unsupported-010` | *"Which Boston game do you mean? I have four Knicks–Celtics games in scope: ..."* | The question itself asks for a disambiguation; the answer lists the four games. Labeled unsupported and not counted as a decline. |
| `comparisons-007` | *"The archive shows four Knicks games against Boston, not two: New York went 3-1"* | The draft question's premise ("the two Knicks games") contradicts the archive's four BOS games (also listed in `single_game_narrative-007`). Per-game comparison is also unavailable, but the false premise alone makes the question unanswerable as written; label status is unreviewed. |

## Passing-but-mis-scoped scan (the 37)

### Strictly `query_resolution.py:389-404`: none

I applied both regexes to all 37 passing questions. The only passing rows that receive a
`game_result` are `exact_statistics-005` (home win), `exact_statistics-006` (road win),
`date_range_last_n-006` (road win in December), `exact_statistics-008` (biggest win), and two unsupported rows (`unsupported-002`, `unsupported-007`)
where no scope executes. All are correct or irrelevant. No passing question combines home with
road/away, and none combines wins with losses. The `win streak` example does not occur: there is no
"streak" question in the 120-row benchmark. The wins/losses collapse fires only on
`comparisons-010`, which fails. So the collapse is not currently masked by a false pass in this
sample.

### Wider resolver (same file, no DB/provider): 5 passing rows are mis-scoped

| id | Why the scope is wrong | Evidence it passed anyway |
| --- | --- | --- |
| `aliases_typos-003` | `season_type` uses substring tests: `"play in" in q` is true for *"How did JB **play in** that game?"* (`query_resolution.py:380-387`), so the scope is play-in games. | Answer: *"The current scope is the 2025-26 play-in, and no specific game is selected."* Passed as `validated`. |
| `date_range_last_n-005` | "All-Star break" has no date branch; the date logic only handles ISO dates, this month, named months and last-N (`query_resolution.py:355-378`), so the scope is the full season. | Answer: *"Which team (or player) do you mean? I can look up the post-All-Star-break record..."* Passed as a clarification. |
| `date_range_last_n-009` | "between March 1 and March 15" has no ISO dates, so the named-month fallback sets the whole of March (`query_resolution.py:369-373`). | Answer asks for the subject; the March window is never used. Passed as a clarification. |
| `date_range_last_n-010` | "first 10 games" does not match `\blast\s+(\d+)\s+games?\b` (`query_resolution.py:359-361`), so there is no window at all. | Answer: *"Which team (or player) do you mean, and should 'first 10 games' mean..."* Passed as a clarification. |
| `comparisons-004` | "first 10 games with their last 10 games": only "last 10" matches, so `relative_count=10` is applied to the whole question and "first 10" is dropped (`query_resolution.py:359-361`, `493-494`). | Answer asks which player/team and which phase. Passed as a clarification. |

Under the ticket's strict "389-404 only" instruction, the list is empty. The five above are the
passing-but-mis-scoped list for the resolver as a whole.

### 12 of the 37 passes are clarifications, not substantive answers

`date_range_last_n-005`, `-008`, `-009`, `-010`, `comparisons-004`,
`single_game_narrative-007`, `-009`, `turning_points-002`, `-004`, `-006`, `-010`,
`aliases_typos-003`.

`meets_expectation` accepts any `validated` outcome for answerable rows
(`tools/release/analyst_live_e2e.py:81-85`), and the reviewer treats questions to the user as
conversational (`analyst_provider.py:282-283`). So the 37/70 is inflated: at most 25/70 are
substantive validated answers. This also explains the inconsistency where the same clarification
behavior is a pass on an answerable row (`single_game_narrative-007`) and a miss on an unsupported
row (`unsupported-009`).

## Caveats

- All labels are `needs_archive_review`. Several rows counted as label/clarification are arguable
  label errors; the counts above follow what the run produced.
- Fallback answers are capped at three claims (`analyst_loop.py:301`), so they always look like
  truncated stat dumps. That is a renderer property, not evidence about the model's answer.
- The provider payload drops claims that do not fit the input budget without a warning
  (`analyst_provider.py:199-231`). `date_range_last_n-007` is the visible symptom.
- The scoring phrase match is narrow (`tools/release/analyst_live_e2e.py:60-66`); "isn't
  available", "falls outside" and clarifications are not declines.

## What this means for the spec

- A correct scope layer alone recovers at most 3 of the 33 recorded misses (9%), all in
  comparisons. Add `comparisons-003` only if the layer also introduces a multi-valued/grouped
  comparison and the tool implements it; otherwise the count stays 3.
- The bigger addressable buckets are tool gaps (16, 48%) and review/provider (7, 21%). The scope
  spec should not claim those, and the E2E target should separate them.
- Fix the harness before using it as the acceptance gate: the 12 clarification passes and the
  decline phrase mismatch (`unsupported-005`) mean a scope change can move the score without
  moving usefulness. The map's "Amend acceptance" ticket should own this.
- The only wrong scope that is currently hidden by a pass is the `play in` substring
  (`aliases_typos-003`). The home/road and wins/losses collapses are visible as failures
  (`comparisons-001/-006/-010`), so they are measurable in the current artifact.

## Machine-readable summary

```text
scope_caused = comparisons-001, comparisons-006, comparisons-010
missing_tool = comparisons-003, comparisons-005, comparisons-009,
               single_game_narrative-001, single_game_narrative-003,
               single_game_narrative-005, single_game_narrative-006,
               single_game_narrative-008, single_game_narrative-010,
               turning_points-001, turning_points-005, turning_points-007,
               turning_points-008, turning_points-009,
               aliases_typos-005, aliases_typos-007
review_provider = exact_statistics-009, date_range_last_n-007, comparisons-002,
                  unsupported-006, unsupported-008,
                  turning_points-003, aliases_typos-010
clarification_correct = single_game_narrative-002, single_game_narrative-004,
                        aliases_typos-008
label_scorer = unsupported-005, unsupported-009, unsupported-010, comparisons-007
passing_mis_scoped_strict_389_404 = (none)
passing_mis_scoped_wider = aliases_typos-003, date_range_last_n-005,
                           date_range_last_n-009, date_range_last_n-010,
                           comparisons-004
passing_clarification_only = date_range_last_n-005, date_range_last_n-008,
                             date_range_last_n-009, date_range_last_n-010,
                             comparisons-004, single_game_narrative-007,
                             single_game_narrative-009, turning_points-002,
                             turning_points-004, turning_points-006,
                             turning_points-010, aliases_typos-003
```
