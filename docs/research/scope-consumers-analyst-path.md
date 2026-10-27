# Scope consumer inventory: analyst path

Part of #39 (parent map #38). Companion to
[`scope-consumers.md`](./scope-consumers.md) and
[`scope-consumers-request-path.md`](./scope-consumers-request-path.md). Line numbers from `d580011`.

The analyst path runs when `analyst_evidence_loop_enabled` is on (`config.py:122`, default
`False`); `analysis.py:112-115` returns from `_query_evidence_analyst` before the request-path
resolver at `analysis.py:168` runs, so the two paths never execute in the same turn.

## Consumers: analyst path

`Path` = `analyst`. Model-supplied scope interacts only through `ToolCall.question`
(`evidence_contracts.py:110`) and the overlay at `analyst_dispatch.py:58-72`.

| Consumer | `ResolvedQuery` fields read | What breaks if model-supplied |
| --- | --- | --- |
| `analyst_tools.py:76-78` `prepare` — the turn's authoritative scope | whole object; then `date_start`/`date_end` (`79-85`), `player_ids` (`104-125`), `player_ids` again for prior-claim admission (`131-139`) | A model scope here *is* the turn scope: `selected_games`, claim admission and the manifest all read it. A hallucinated player id silently empties `self.rows`; a hallucinated date range empties `selected_games` and the turn degrades to `no_matching_results` (`analyst_dispatch.py:78-85`). Prior claims are admitted only if `subject_id in {"player:<pid>"}` for the scope's players (`138-139`), so a wrong id drops valid prior work. |
| `analyst_tools.py:86-103` prior-turn merge | `player_ids`, `season_type`, `opponent_id`, `home_away`, `game_result` (skips `game_result` for record requests, `97-98`) | Merge is "fill if the current regex found nothing". A model scope plus a follow-up text would need the same truthiness contract; today a model `home_away` would be inherited into later turns and then written back into `state["scope"]` (`126`). |
| `analyst_tools.py:169` `manifest` | full `model_dump` | The model reads its own scope back from the tool manifest; any unverified value becomes self-reinforcing context. |
| `analyst_tools.py:172-189` `selected_games` | `game_ids`, `season_type`, `date_start`, `date_end`, `opponent_id`, `home_away`, `game_result` | This is the single place the collapse bites: with `home_away="home"` the population is home games only even when the question asked for both (`181`), and `game_result="W"` drops losses (`183-188`). Every analyst claim, evidence list and window below this inherits the truncated population. |
| `analyst_tools.py:243` `claim` → `filters` (`284-288`) | `opponent_id`, `home_away`, `game_result`, `periods` | A model-supplied value is persisted into `VerifiedClaim.filters` and replayed as provenance. A wrong `game_result` here mislabels a claim permanently and survives across turns (`130-149`). |
| `analyst_tools.py:327-329` `search` | `planner_filters()`: `player_ids`, `team_ids`, `game_ids`, `periods`, `season_type`, dates | Same six-field limit; model scope for venue/outcome cannot be expressed, so `search_archive` results are never venue- or outcome-filtered. |
| `analyst_dispatch.py:30-35` | `requires_clarification`, `clarification_options` | A model that can abstain via scope can short-circuit every tool to `ambiguous_entity` before any evidence exists; the choices are echoed verbatim to the user. |
| `analyst_dispatch.py:49-51` | none read — resolves a *second* scope from `call.question` | Model-authored `call.question` is re-resolved by the same regexes, so a model that paraphrases "home and road" as "home" loses the road half twice. |
| `analyst_dispatch.py:58-72` | `player_ids`, `game_ids`, `season_type`, `opponent_id`, `home_away`, `game_result`, `date_start`, `date_end`, `periods`, `relative_game_count` (overlay) | The regex value wins whenever it is truthy, so a correct model correction is discarded and an incorrect regex value is enforced. Conversely, when the regex found nothing the model value survives unreviewed. |
| `analyst_dispatch.py:73-77` | `periods` | Any non-empty value turns every calculation tool into `unsupported_metric_or_scope`, except `search_archive`. A model that adds a period kills the turn's arithmetic. |
| `analyst_dispatch.py:92-97` | `player_ids` | Empty → hard stop asking "Which Knicks player?" with all rostered names; a model scope must decide this before any query runs. |
| `analyst_dispatch.py:98` | `metric` | Fallback chain `call.metric or scope.metric or "points"`. Model metric is schema-restricted to the `METRICS` literal set (`evidence_contracts.py:111-124`), so this field is already safe to model-supply; the regex `scope.metric` is likewise closed (`query_resolution.py:43-59`). |
| `analyst_dispatch.py:111-118` `compare_windows` | none read; injects `player_ids` into the baseline scope (`115`) | The baseline is a fresh regex resolution of the model's `baseline_question`, forced to the current turn's players. If players become model-supplied, the baseline inherits them unchecked. |
| `analyst_calculations.py:30-31`, `42-43` | `relative_game_count` | Applied twice (game slice, then row slice). A model-supplied N changes sample size and the average denominator (`46-49`) with no textual anchor; a too-large N silently widens the window. |
| `analyst_calculations.py:35`, `60`, `90` | `player_ids`, `season_type`, full dump | `season_type` is interpolated into the user-facing statement (`60`), so a wrong value produces a confidently mislabelled answer. |
| `analyst_calculations.py:100-103`, `123` | `relative_game_count`; full dump | Record requests drop non-final games first (`101`), then slice — order matters if scope becomes time-ordered by the model rather than by the archive. |
| `analyst_discovery.py:28-29`, `129` | `player_ids` | Restricts the candidate pool; empty means "all players". A model-supplied id that is not in `tools.rows` yields an empty pool and `no_matching_results` ("No undelivered eligible facts match this scope", `309-312`) — which reads like exhaustion, not error. |
| `analyst_discovery.py:36`, `88-90`, `131` | `metric` | Selects which stat to score and which catalog facts pass the `stat_keys` filter; values are validated against `METRICS` before use. |
| `analyst_discovery.py:155`, `316` | full dump | Same provenance surface as `claim`. |
| `analyst_fallback.py:30-46` | `requires_clarification`, `periods`, `player_ids`, `relative_game_count`, plus `selected_games` (`42`) | Fallback answers reuse existing claims only when the population matches the scope (`47`). A model-supplied scope with no evidence behind it makes the fallback refuse to answer even when valid prior claims exist. |
| `analyst_loop.py:280` | `player_ids` | Chooses `get_player_stats` vs `get_team_stats` for recovery (`278-283`), i.e. a scope value decides which tool runs when the model fails. |
| `analyst_loop.py:365-366` | writes `state["scope"]["player_ids"]` + `scope_origin="delivered_subject"` | Delivered subjects overwrite the persisted scope; if the model supplies scope, this write and the model's own claim set can diverge with no conflict check. |
| `analyst_provider.py:177` | the dumped `scope` of every `ToolResult` | The model sees the regex filters as ground truth for its next proposal, closing a loop between regex scope and model planning. |
