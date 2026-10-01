# Ten-message game references

Written before the HTTP E2E checks and implementation. The owner clarified:
“that” must refer to a game identified in the same last-ten-message conversation;
otherwise ask which game. This supersedes the premature identity-relevance stop.
The original release contract, semantic cohort, costs and approval gates remain.

Failures to prevent:

- With no context, “How did JB play in that game?” becomes a season average or
  uses an arbitrary game's performance instead of “Which game?”
- A concrete, canonical game/date inside the last ten messages is ignored.
- A game/date late in an older in-window message disappears when the model's
  2,000-byte history excerpt is shortened. Deterministic identity resolution
  must use all ten validated messages without enlarging the model prompt.
- A changed in-window game/date reuses a committed response because the changed
  identity was outside the model excerpt used to bind the session replay.
- A game in message eleven or stale server scope survives the ten-message window.
- Two games in the latest identifying message are collapsed into one default.
- A newer unavailable game/date silently falls back to an older game reference.
- A newer identified game retains the older game's statistics or player metric.
- Opponent-only or unverified assistant narrative becomes a unique game anchor.
- A context message's unsupported score or player performance becomes a fact;
  context can identify a target, but answers still use active-release SQL rows.
- A reference to another release, wrong season, nonexistent date or contradictory
  current opponent is accepted without canonical validation.
- A missing/ambiguous game invokes a model, creates a budget reservation, loses
  session/revision identity, changes replay, or allows a changed replay payload.
- Failure evidence is omitted. Every HTTP case writes request, response,
  capture, replay, conflict, model-attempt count and real Redis budget receipt
  before assertions, and existing artifacts are never overwritten.

Verification uses the actual ASGI HTTP route, seeded SQL and dedicated local
Redis. It covers all four disabled/primary/shadow admission modes for missing
anchors; supported scoped answers use disabled mode to prohibit paid dispatch.
These are product regression checks, not a frozen 120-case quality evaluation.
