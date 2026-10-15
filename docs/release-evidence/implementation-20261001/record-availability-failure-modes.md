# Record availability regression

Written before the production fix for `exact_statistics-001`.

- A writer can clarify the team or season phase before requesting the available record.
- A writer can omit both record claims after the backend prepares them.
- A writer can provide only wins or only losses, leaving an incomplete record.
- A calculation can silently widen a regular-season, playoff, month, opponent, or last-N request to the full archive.
- A calculation can substitute the current archive for an unavailable season.
- An unresolved player reference can be mistaken for a team record request.
- A repeated HTTP turn can call the provider again, change its response, or change the Redis budget.

The socket HTTP regression uses the public analysis route, a loaded SQL release, an isolated Redis process, and a scripted provider that never asks for tools. It retains full requests, responses, model inputs, tool traces, replay evidence, and independent archive-derived expectations. The approved archive run must report 69 wins, 32 losses, and the exact 101-game population. The default fixture remains synthetic for CI. Neither run proves live model quality or release readiness.
