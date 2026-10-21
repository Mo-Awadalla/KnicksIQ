# Adding a tool: one module plus one registry entry

Demonstrated on `codex/llm-registry` in a scratch working state, then removed. Nothing from the
demo is committed.

## The two edits

New file `apps/api/app/services/analyst_tool_scratch.py` (23 lines) exposing:

```python
async def run(tools, call, scope, games) -> ToolResult:
    return ToolResult(status="ok", message="scratch tool executed")
```

One entry appended to `TOOLS` in `apps/api/app/services/analyst_tool_registry.py`:

```python
    ToolSpec(
        name="scratch_echo",
        description="echoes for the registry demo",
        handler="app.services.analyst_tool_scratch:run",
        needs_scope=False,
        needs_games=False,
    ),
```

## Observed with the entry present

```text
accepted: scratch_echo
schema tail: ['get_evidence', 'scratch_echo']
hint has tool: True
dispatch: ok scratch tool executed
registry names: ('get_player_stats', 'get_team_stats', 'compare_windows', 'discover_facts',
                 'search_archive', 'get_evidence', 'scratch_echo')
unknown rejected: literal_error
```

The name validated through `ToolCall`, appeared at the end of the `Action` schema enum, appeared in
the generated provider prompt without editing `analyst_provider.py`, and dispatched through
`execute_call` without editing `analyst_dispatch.py`.

## After removal

```text
names: ('get_player_stats', 'get_team_stats', 'compare_windows', 'discover_facts',
        'search_archive', 'get_evidence')
scratch absent: True
rejected after removal: literal_error
no scratch files
```
