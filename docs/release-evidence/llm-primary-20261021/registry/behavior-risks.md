# Registry refactor behavior risks

Base: `d5800118b497e92e5e5609c7b66404d930e1e2fb` (`codex/production-ready-20261018`).
Branch: `codex/llm-registry`.

The refactor replaces three shared edit points (the `ToolCall.name` Literal, the dispatch if-chain,
the system prompt tool list) with one typed registry. The only accepted change is structure, never
observable behavior for the six existing tools. Ways it could silently change behavior:

1. Prompt text drift. The provider system prompt is model input. Any changed word, punctuation,
   capitalization, ordering or whitespace changes the model's behavior even though tests pass.
   The generated hint must reproduce the base string byte for byte; prove it by hashing the string
   sent by both revisions, not by reading the source.
2. Schema enum order. The `name` enum in the JSON schema sent to the provider follows Literal
   argument order. Reordering registry entries reorders the enum and can bias sampling. Keep the
   base order: get_player_stats, get_team_stats, compare_windows, discover_facts, search_archive,
   get_evidence. Verify the full `Action.model_json_schema()` is byte-identical, not only the enum.
3. Dynamic Literal shape. Building `Literal[*TOOL_NAMES]` at runtime must render the same schema as
   the hand-written Literal: an inline `enum` with `type: string`, not a `$ref`, `const` or a
   string field with a validator. A changed schema changes constrained decoding and validation.
4. Prompt lead special case. `discover_facts` sits in the first sentence, not in the semicolon
   list. Moving it into the list, or emitting a second "call discover_facts" clause, changes the
   prompt. It must stay exactly one sentence in the same position.
5. Periods guard scope. Base rejects `scope.periods` for every tool except search_archive. If
   `supports_periods` defaults to true, turns that should decline start returning full-game totals
   labeled as quarters. If it defaults to false for search_archive, narrative retrieval regresses.
6. get_evidence ref checks. Base validates every requested id against issued ids before anything
   else and returns only prior evidence. If get_evidence becomes scope-resolved, clarification or
   season checks can hijack a reference expansion, and evidence ids become resynthesizable.
7. Check ordering. Base order is get_evidence, clarification, season, resolve, authoritative merge,
   periods, empty games, dispatch, player requirement. A different order changes status and
   message for edge cases (for example an ambiguous scope plus an unavailable season).
8. Authoritative merge. The nine user-scope keys must still override the locally resolved scope
   with the same truthiness rule and in the same place. Dropping a key lets the model narrow to a
   season or opponent the user did not authorize.
9. Player requirement. Base asks "Which Knicks player?" only for player and comparison tools,
   after team/discovery/archive dispatch. If `needs_player` leaks to team or discovery, ordinary
   team questions start clarifying; if it is missing on compare_windows, comparisons crash or
   answer for an arbitrary player.
10. Metric stripping. `PLAYER_METRIC_TOOLS` drops `metric` from calls to tools that ignore it. It
    must remain exactly the tools that read `metric` (player and compare). Deriving it from
    `needs_player` couples two concepts; a future player-facing tool that does not read metric
    would silently stop stripping, and a team metric such as "wins" would abort the turn again.
11. compare_windows internals. The baseline season guard, baseline scope resolution, forced player
    ids, missing-population `incomplete_coverage` result and delta claim construction must move
    unchanged. Rounding, claim ids, ordering of returned claims and evidence are observable.
12. Fallback recovery. When validation fails, base picks discovery, then player when a player is
    in scope, else team, and uses totals for team and averages otherwise. A role flag that picks
    a different tool or aggregation changes the fallback answer text and cost.
13. Handler import cycles. A registry that imports tool modules while `evidence_contracts` imports
    the registry creates a circular import at process start. Resolution must stay lazy and must
    not reorder module initialization.
14. Error mapping. `AnalystTools.execute` converts any raised exception to `dependency_failure`
    with `"<name> unavailable"`. Handler resolution and handler raises must keep that behavior;
    they must not escape as a 500 or as absence of data.
15. Status, message and scope payloads. Text returned to the model (for example "These
    calculations support full-game box scores only." and "No archived games match this scope...")
    is prompt input. Wording and `scope` dict contents must not change.
16. Tool name acceptance. Unknown names must still fail validation as a Literal error. A plain
    string field with a membership check is not equivalent if it accepts coercion or changes the
    error shape.
17. Empty-game precedence. Base resolves games and returns `no_matching_results` before player
    clarification and before handler dispatch. Moving it after the player check changes which
    status the model sees for an empty population.
18. Registry order coupling. The prompt list, Literal enum, dispatch lookup and fallback scan all
    read one ordered tuple. Any accidental sort (for example iterating a set) changes enum order
    and prompt order.
19. Test count. The suite must stay at the base count (392 passed). A refactor that deletes or
    skips a tool-name test hides a regression rather than removing one.
