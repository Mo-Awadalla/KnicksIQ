# Who consumes regex scope, and which fields

Research note for #39, parent map #38. Inventory only: no application code changed. Line numbers
are from `d580011`. `[INFERENCE]` marks claims not directly observed in code.

## Summary table

Every consumer group, the scope surface it touches, and the path it runs in. Detail (fields read
per line, and the failure mode of each) is in the two linked inventory notes.

| Consumer group | Scope surface | Path | If the field becomes model-supplied |
| --- | --- | --- | --- |
| `analysis.py:168-230` request resolver, refusal gate and clarification | `intent`; then `player_ids`, `team_ids`, `game_ids`, `date_start`, `date_end`, `relative_game_count`, `periods`, `metric` for `resolved_supported`; `requires_clarification`* | request (all modes) | Populating scope suppresses the off-topic refusal (`286-300`); a model abstention pre-empts retrieval (`204-225`). |
| `analysis_retrieval.py:264-273`, `analysis_player_response.py:83` filter overlay | `planner_filters()` only | `llm_primary` | The model's plan filters are replaced wholesale; `home_away`, `game_result`, `opponent_id`, `metric`, `relative_game_count` can never be expressed. |
| `analyst_tools.py:76` `prepare` + `:172-189` `selected_games` | whole object | analyst | The turn population, prior-claim admission and manifest all follow it; one bad id or range empties the turn. |
| `analyst_dispatch.py:58-72` overlay | 10 fields, truthy-wins | analyst | Regex overrides a correct model value and enforces a wrong one; regex cannot widen to "both". |
| `analyst_calculations.py`, `analyst_discovery.py` | `player_ids`, `relative_game_count`, `metric`, `season_type`, full dump into claims | analyst | Denominators, sample sizes and user-facing statements change; `home_away`/`game_result` are persisted into claim provenance. |
| `fact_discovery.py:116-192` | whole object, applied as a game/row filter | request (`discover_fact`) | The mined population inherits the collapse; `periods` and unresolved subjects are refused (`128-145`). |
| `conversation_state.py:45-108` | 12 of 17 fields | both | Stored in and replayed from client state; inheritance is fill-blanks with three-field topic detection. |
| `classify_query` consumers (`analysis.py:383`, `analysis_policy.py:207`, `narrative_scope.py:50,141`) | `kind`, `is_aggregative` (no scope) | request | `is_aggregative` alone picks table vs narrative and gates refusal — an answer-shape decision, not a filter. |
| `answer_cache_key` (`runtime_store.py:15-40`) | none directly | both | Safe while scope is a pure function of text + release; collides if the resolver becomes model-dependent. |

\* `requires_clarification` / `clarification_options` are read at `analysis.py:204-225` and
`analyst_dispatch.py:30-35`.

## Where the detail is

- [`scope-consumers-analyst-path.md`](./scope-consumers-analyst-path.md) — analyst path, line by
  line: `AnalystTools`, `analyst_dispatch`, `analyst_calculations`, `analyst_discovery`,
  `analyst_fallback`, `analyst_loop`, `analyst_provider`.
- [`scope-consumers-request-path.md`](./scope-consumers-request-path.md) — request path, line by
  line, plus the `classify_query` and `ConversationState` consumer tables and the per-field reach
  matrix.


## Structure: two mutually exclusive paths

- **Analyst path** — gated by `analyst_evidence_loop_enabled` (`config.py:122`, default `False`).
  `analysis.py:112-115` returns from `_query_evidence_analyst` before the request-path resolver at
  `analysis.py:168` ever runs. The analyst resolves scope itself at `analyst_tools.py:76-78`.
  `analysis_sessions.py:84-90` allows model calls only when `analysis_answer_mode == "llm_primary"`
  or a shadow sample fires, but `AnalystTools.prepare` resolves the regex scope in every mode.
- **Request path** — `analysis.py:168-230` builds `ResolvedQuery` (optionally folded with prior
  `ConversationState` at `analysis.py:199-203`), then dispatches to table / narrative / player
  modules. `resolve_query` runs here only when `rag_query_resolution_v2_enabled` or
  `rag_structured_conversation_state_enabled` is set (`analysis.py:169-171`; both default `False`
  at `config.py:106,115`).

Two structural facts drive the whole inventory:

1. **Only 6 of the 17 `ResolvedQuery` fields can reach a retrieval filter.** `planner_filters()`
   (`query_resolution.py:118-134`) emits `dates`, `team_ids`, `player_ids`, `game_ids`, `periods`,
   `season_types` — nothing else. `opponent_id`, `relative_game_count`, `home_away`, `game_result`,
   `metric`, `intent`, `data_version`, and the three clarification fields are silently absent.
   `_apply_resolved_filters` (`analysis_retrieval.py:264-273`) *replaces* the plan's filters with
   that dict, so in `llm_primary` any filter the model planner proposed is discarded, not merged.
2. **The two collapsing fields are calculation-only.** `home_away` and `game_result` are never in
   a retrieval filter; their only effect is in analyst game selection (`analyst_tools.py:172-189`,
   `fact_discovery.py:158-174`) and claim provenance (`analyst_tools.py:284-288`). A `llm_primary`
   archive-retrieval turn therefore cannot see the collapse in its evidence, and a deterministic
   table turn never sees `ResolvedQuery` at all — `team_scope.scope_games` re-derives venue from
   the text and correctly keeps both sides when both words appear
   (`team_scope.py:50-52`: `home != away` gates the filter).

## Answer cache

`answer_cache_key` (`runtime_store.py:15-40`) hashes
`ANSWER_CACHE_SCHEMA_VERSION ("v3") | normalized question | season | data_version | index_version |
model_version | answer_mode | prompt_version` with `ip_hash_secret` (schema version and field order
at `runtime_store.py:12,26-37`). Call site: `analysis.py:344-359`.

- **Scope enters only through the question string.** When `rag_structured_conversation_state_enabled`
  is on and the request carries state, `analysis.py:346-352` appends `"\nstate:" +
  req.conversation_state.model_dump_json()` to the hashed question. So a scope difference is a
  cache miss *only if* it arrived as client state.
- **`resolved_query` is never a key input.** Today that is sound because `resolve_query` is a pure
  function of (question, active release, data version) and both text and `data_version` are in the
  key. If scope becomes model-supplied, the same question can map to different scope on different
  attempts and the key would still collide — `model_version` would need to carry the resolver
  identity, or the resolved scope must be added to the payload.
- **Cache is skipped for multi-turn requests** unless structured state is enabled
  (`analysis.py:345`), so context-derived scope is not cached in the default configuration.
- **Cached answers are only written when not degraded** (`analysis.py:481-482`, `507-508`), and a
  cached non-degraded answer short-circuits planning entirely (`analysis.py:360-380`), including
  the shadow comparison plan that reuses `deterministic_retrieval_plan` (`analysis.py:371-375`).
- `data_version` and `index_version` are both populated from `response_metadata["data_version"]`
  (`analysis.py:353,358`), so a release change invalidates the cache; a *scope* change does not.

## Findings relevant to the decision

1. **The collapse is invisible where the failures were measured.** In the `llm_primary` request
   path, `home_away` and `game_result` never reach a retrieval filter, so the evidence for a
   "home and road" turn is unfiltered; the collapse only bites the analyst path's populations and
   the claims' `filters` metadata. Any fix that only changes `resolve_query` would change nothing
   for `llm_primary` retrieval. [INFERENCE] from the per-consumer tables in the two linked notes.
2. **`ResolvedQuery` needs a "both" representation before it can be model-supplied.** Every
   consumer that reads `home_away`/`game_result` compares against a single literal
   (`== "home"`, `== "W"`, `== (scope.game_result == "W")`); none can distinguish "not asked"
   from "both sides". Moving the source of these two fields without changing their type keeps the
   same defect, and the current single-value behaviour is pinned by tests
   (`test_reliability_release.py:61-88`, `test_query_resolution.py:51-62`).
3. **The overlay direction is one-way.** `analyst_dispatch.py:58-72` lets the regex scope overwrite
   the model whenever the regex is truthy, and `analysis_retrieval.py:270-273` replaces model
   filters outright. A model-first design must invert both, not just the producer.
4. **There are already two scope parsers in the request path.** `ResolvedQuery` and
   `deterministic_retrieval_plan` both parse the question, and `team_scope.scope_games` parses it a
   third time for table/narrative answers (`team_scope.py:40-67`). The third one handles
   "home and road" correctly by keeping both sides; the first does not. Any cutover must retire or
   align all three.
5. **The cache needs a scope input only if the resolver stops being a pure function of the text.**
   `answer_cache_key` (`runtime_store.py:15-40`) already covers release and model identity, and
   `resolved_query` is not hashed today.
6. **Dead code worth deleting in the same change:** `ResolvedQuery.retrieval_filters`
   (`query_resolution.py:105-116`) has no production call site; `planner_filters` is the only
   filter projection in use (`analysis_retrieval.py:272`, `analysis_player_response.py:69`,
   `analyst_tools.py:328`).
