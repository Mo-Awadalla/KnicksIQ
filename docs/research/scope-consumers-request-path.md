# Scope consumer inventory: request path, classifier, conversation state

Part of #39 (parent map #38). Companion to
[`scope-consumers.md`](./scope-consumers.md) and
[`scope-consumers-analyst-path.md`](./scope-consumers-analyst-path.md). Line numbers from `d580011`.

`request` means the non-analyst path (`analysis.py:168` onward) in `deterministic`, `shadow` or
`llm_primary` mode. `classify_query` is listed separately because it never sees `ResolvedQuery`.

## Consumers: request path (`analysis.py` and friends)

`Path` = `request` unless noted. These run in `deterministic`, `shadow` and `llm_primary` alike,
except where `llm_primary` is called out.

| Consumer | `ResolvedQuery` fields read | What breaks if model-supplied |
| --- | --- | --- |
| `analysis.py:172-178` producer | `classify_query(question).kind` → `intent` | `intent` is only echoed (see classifier table). Low risk. |
| `analysis.py:181-198` prior state | runs a second `resolve_query` over the last user turn, then `state_from_resolved` (`198`) | A model-supplied scope for the *current* turn combined with a regex-derived prior turn creates a hybrid state (model now, regex history). Any inheritance bug is then invisible. |
| `analysis.py:199-203` `resolve_conversation_delta` | see conversation-state table | Follow-up inheritance would mix model and regex origins per field; `ConversationState` has no origin marker, so provenance is lost (`state["scope_origin"]` exists only in the analyst path, `analyst_tools.py:127`). |
| `analysis.py:204-225`, `226-230` | `requires_clarification`, `clarification_options`, `clarification_reason`, full dump into `response_metadata` | A model abstention would pre-empt retrieval entirely and render `route="clarification"`; the dump is echoed to clients outside production (`analysis_models.py:100-103`). |
| `analysis.py:286-300` `resolved_supported` | `player_ids`, `team_ids`, `game_ids`, `date_start`, `date_end`, `relative_game_count`, `periods`, `metric` | This is the refusal gate: any truthy field makes a question "supported". A model that populates scope for an off-topic question suppresses the refusal path at `analysis.py:322-341`; `home_away`/`game_result`/`opponent_id` are notably *not* read here, so scope can be non-empty and still count for nothing. |
| `analysis.py:426` → `analysis_retrieval.py:264-273` (`llm_primary` only) | `planner_filters()`: `player_ids`, `team_ids`, `game_ids`, `periods`, `season_type`, dates (single-day only, `query_resolution.py:105-116`) | Wholesale replacement of the plan's filters: model filters are lost unconditionally, and six scope fields can never be expressed. Venue/outcome asks retrieve unfiltered evidence. |
| `analysis_retrieval.py:69-160` `_execute_archive_retrieval` | the resulting `RetrievalPlanFilters` | Filters are applied per collection: `dates`/`game_ids`/`season_types`/`team_ids` on games (`archive_retrieval.py:131-142`), `player_ids` on box scores (`326-328`), `periods`/`player_ids` on possessions (`365-369`). `periods` is ignored for the games collection, so a period-scoped question still retrieves whole-game docs. |
| `analysis_player_response.py:48-49` (all modes) | `player_ids`, `game_ids` | Passed into `answer_player_question`; `player_ids` only used when textual resolution fails (`player_analytics.py:116-118`), and `game_ids` hard-filters games and rows (`233-236`). A model-supplied `game_ids` silently narrows a season average to one game with no textual trace. |
| `analysis_player_response.py:63-72`, `83` | `planner_filters()` | Builds the fallback plan, then `_apply_resolved_filters` overwrites the model's plan with the same six fields (`83`). |
| `analysis_player_response.py:117-122` | `player_ids[0]` when exactly one | Attaches a `player_id` to every structured claim; with a multi-player model scope the field goes `None` and claims lose their subject. |
| `analysis_table_response.py:43`, `112-116` | none; `deterministic_retrieval_plan(question, ...)` only | Table answers re-derive scope from text via `table_rag.answer_table_question` → `scope_games` (`table_rag.py:32`). If scope moves to the model, this module keeps using the old text regexes unless changed — two scope sources answering the same turn. |
| `analysis_narrative_response.py:53`, `79-96`, `253-257` | none; `deterministic_retrieval_plan` for the shadow plan | Same: scope comes from `scope_games` (`analysis_retrieval.py:47`) and `search_possession_chunks`' own filters, not from `ResolvedQuery`. |
| `fact_discovery.py:116-121` | whole object → `state_from_resolved`; `122-127` clarification; `128-133` `periods`; `136-145` `player_ids`; `158-174` `game_ids`, `season_type`, `opponent_id`, `date_start`, `date_end`, `home_away`, `game_result`; `188-192` `player_ids` | Same filter shape as `selected_games`, so the same collapse: "interesting stat in home and road games" would mine home games only. It is the only request-path module that applies `home_away`/`game_result` to a population. |
| `retrieval_planner.py:46-86` `deterministic_retrieval_plan` | none — takes `question`, `intent`, `is_aggregative` | Call sites: `analysis.py:310-314` (unsupported pre-plan), `analysis.py:371-375` (shadow on cache hit), `analysis.py:412-416` (llm_primary fallback), `analysis_table_response.py:112-116` (shadow), `analysis_narrative_response.py:253-257` (shadow). Its filters are regex-derived from the text and are later replaced by `_apply_resolved_filters` in `llm_primary` (`analysis.py:426`). If scope is model-first, this second parser stays behind as a divergent path. |
| `retrieval_planner.py:89-112` `_filters_are_grounded` | n/a (guards model output) | The existing model-supplied-filter guard: teams/dates/periods/season types must appear literally in the question, and `return not plan.filters.player_ids and not plan.filters.game_ids` (`112`) forbids model entity ids outright. Any model-first scope has to pass through this or replace it deliberately. |

## Consumers: `classify_query`

`classify_query` returns `kind`, `is_aggregative`, `confidence`, `signals`
(`query_classifier.py:64-105`). It is called on raw text, never on scope.

| Consumer | Fields read | Path | What breaks if replaced by a model |
| --- | --- | --- | --- |
| `analysis.py:172` | `kind` → `ResolvedQuery.intent` | request | `intent` is only echoed (`conversation_state.py:107` writes it to `route`; `analysis_models.py:100-103` exposes the dump outside production). Almost free to move. |
| `analysis.py:195` | `kind` for the reconstructed prior turn | request | Same. |
| `analysis.py:309-314` | `kind`, `is_aggregative` for the unsupported pre-plan | `llm_primary` only | Decides whether an out-of-domain question is even planned; a wrong `is_aggregative` changes collections and `fact_tools` in the fallback plan. |
| `analysis.py:363-375` | `kind`, `is_aggregative` on the cache-hit shadow path | `shadow` | Only affects logged comparison. |
| `analysis.py:383-385` | `is_aggregative` → `route = "table_rag" if ... else "retrieval_rag"` | request | The route switch: this single boolean decides whether the table or narrative module answers. A model that misclassifies here changes the answer shape, not just filters. |
| `analysis_policy.py:207` | `is_aggregative` | request | Part of the supported-question gate (`_is_supported_question`); a model verdict here could widen or suppress refusal — a policy decision, not a planning detail. |
| `narrative_scope.py:50`, `141` | `is_aggregative` | request | Decides whether a question is a narrative reference needing clarification or a metric question that should fall through. |

## Consumers: `ConversationState` / `state_from_resolved`

| Consumer | Fields read | Path | What breaks if model-supplied |
| --- | --- | --- | --- |
| `conversation_state.py:95-108` `state_from_resolved` | `player_ids`, `game_ids`, `opponent_id`, `date_start`, `date_end`, `periods`, `season_type`, `home_away`, `game_result`, `metric`, `intent`, `data_version` | both | The projection is total, so every scope field becomes persisted client state; whatever the model sets is stored and echoed back on the next request. |
| `conversation_state.py:45-92` `resolve_conversation_delta` | reads `player_ids`, `opponent_id`, `game_ids` for subject-change detection (`55-59`); writes nine fields from the prior state when the question is a follow-up (`76-91`); may set clarification (`61-74`) | request | Inheritance is "fill blanks only", with topic-change detection keyed on three fields. A model scope that is *partially* filled will inherit the rest from a prior, unrelated turn; venue and outcome changes are not detected as topic changes at all. |
| `analysis.py:181-203` | `prior_state`, then folded result | request | See above. |
| `analysis.py:237`, `266` | `req.conversation_state.game_ids` | request | Feeds narrative clarification; a model-supplied `game_ids` list makes the clarifier treat those games as the reference set. |
| `analysis_models.py:55`, `104` | whole model | request/API | Client-supplied and client-returned; validated only by field types, so any accepted value is trusted on the way back in. |
| `fact_discovery.py:64`, `78-91`, `119-121` | `data_version`, `discovery_question`, `seen_fact_ids`; then overwrites them | request (`discover_fact` route) | `data_version` gates whether prior seen-facts apply (`78`). This is the only place `ResolvedQuery.data_version` is read as state, and it is compared against the active release, not trusted. |
| `analyst_tools.py:86-103`, `126-128` | a plain dict `state["scope"]` with the same keys | analyst | The analyst path re-implements inheritance on a dict with a different key set (`player_ids`, `season_type`, `opponent_id`, `home_away`, `game_result` only — no dates, periods, metric) and adds `scope_origin` (`127`). Two inheritance implementations, diverging semantics. |
| `analysis_sessions.py:72`, `91`, `117` | `turn.state` in/out | analyst | Turn state is committed server-side per revision; a model scope that changes between retries changes the committed state. |
| `apps/web/src/features/knicks/use-analyst.ts:267-268`, `apps/web/src/api/index.ts:104-114` | full `conversation_state` object | client | The browser stores and replays the object verbatim. Any field added to the state is silently accepted from the client, so nothing in the state can be treated as server-verified without re-validation. |

## Field reach, at a glance

| Field | Analyst readers | Request-path readers | In retrieval filters | Note |
| --- | --- | --- | --- | --- |
| `intent` | manifest dump | echo, `ConversationState.route` | no | Lowest-risk field to move. |
| `player_ids` | prepare, selected_games admission, dispatch 92, calculations, discovery | supported gate, planner filters, player analytics, fact discovery | yes | Already merged with model ids in player analytics (`player_analytics.py:116-118`). |
| `team_ids` | — (only via `planner_filters` in `search`) | supported gate, planner filters | yes | Both filter and gate; `team_ids` excludes NYK (`query_resolution.py:350`). |
| `opponent_id` | selected_games, claim filters, prior merge | fact discovery only | **no** | Retrieved evidence is never opponent-filtered. |
| `game_ids` | selected_games, prior merge, claim admission `131-139` | supported gate, planner filters, player analytics | yes | Forbidden from model plans (`retrieval_planner.py:112`). |
| `date_start`/`date_end` | selected_games, range reset `79-85` | supported gate, fact discovery, planner filters (single day only) | partially | Multi-day ranges are dropped by `planner_filters` (`118-134`). |
| `relative_game_count` | calculations `30-31,42-43`, fallback `45-46`, dispatch overlay | supported gate only | **no** | Never filters retrieval; only slices analyst populations. |
| `periods` | dispatch hard-stop `73-77`, claim filters, search | supported gate, planner filters | yes (possessions only) | Ignored for the games collection (`archive_retrieval.py:131-142`). |
| `season_type` | selected_games, calculations statement, prior merge | supported gate, planner filters, fact discovery | yes | Model plans must ground it in text (`retrieval_planner.py:102-110`). |
| `home_away` | selected_games `181`, claim filters, prior merge | fact discovery `166` | **no** | Single-valued; collapses "home and road". |
| `game_result` | selected_games `183-188`, claim filters, prior merge | fact discovery `168-174` | **no** | Single-valued; collapses "wins or losses". |
| `metric` | dispatch `98`, discovery `36,88,131` | supported gate | **no** | Closed vocabulary on both sides. |
| `requires_clarification` | dispatch `30-35` | `analysis.py:204-225`, fact discovery `122-127` | no | Pre-empts all tool work. |
| `clarification_reason` | — | `analysis.py:212` (warning) | no | Display only. |
| `clarification_options` | dispatch `34` | `analysis.py:205,222` | no | Rendered to the user as `choices`. |
| `data_version` | `conversation_state.py:108` only | `ConversationState` echo, fact discovery `78` | no | Output, not input: the release pin comes from `_active_release` (`query_resolution.py:307-309`) and `tools.release.version` (`analyst_tools.py:76-78`), never from scope. |

## Tests that pin the contract

These are consumers in the ordinary sense: they fail if the field semantics change.

| Test | What it pins |
| --- | --- |
| `test_query_resolution.py:51-62` | One question yields `home_away="away"`, `game_result="W"`, `periods=[3, 4]` together. Only single-value questions are covered; no test covers "home and road" or "wins or losses", so the collapse is untested rather than asserted. |
| `test_query_resolution.py:166-189` | `_apply_resolved_filters` replaces model filters: a plan with `player_ids=[999], game_ids=[999]` comes out as `[11]`/`[22]` from the resolved scope. This is the executable statement of "regex beats model" in retrieval. |
| `test_reliability_release.py:46-59` | A record question leaves `game_result is None` and counts wins and losses over the same population (2+1 over 3 games), i.e. `is_record_request` is what prevents the `W` collapse. |
| `test_reliability_release.py:61-78` | Explicit subsets still collapse: "show only wins" → `W`, "in losses" → `L`, "Brunson's stats in wins" → `W`. |
| `test_reliability_release.py:81-88` | A record follow-up clears only `game_result` while keeping `home_away="home"` and `opponent_id="BOS"` inherited from the prior turn — single-value venue plus fill-blanks inheritance, pinned. |
