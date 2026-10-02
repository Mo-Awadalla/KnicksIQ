# Local Docker verification failure modes

Written before the local container smoke harness. These checks exercise the real
HTTP service, PostgreSQL archive, and Redis conversation store; they do not use
unit-test fixtures or model providers.

- A verification URL accidentally targets hosted production, follows a redirect,
  or sends local requests through a configured HTTP proxy. Accept literal loopback
  HTTP origins only, disable redirects, and bypass ambient proxy settings.
- The normal Compose file imports provider credentials, enables model work, or
  shares an existing database. Use the separate isolated local staging project,
  explicit mock provider, deterministic answers, disabled planner/vector service,
  empty credentials, and dedicated PostgreSQL/Redis volumes.
- An image is alive but migrations or the approved archive are absent. Require
  direct and web-proxied readiness, the pinned release version, 101 games and 101
  reports, and representative game/report detail reads.
- Redis is configured but unavailable. A successful analyst response must include
  a committed session and revision, and replaying the identical turn must return
  the exact saved response. Readiness alone is insufficient proof.
- A retried turn runs again, changes its result, or accepts changed input. Check
  exact replay and HTTP 409 for changed input with a reused turn identifier.
- A new request overwrites a later committed revision. Check HTTP 409 for a stale
  revision and preserve the original successful response for restart verification.
- An unbound reference invents a game, or a bound reference loses its game. A fresh
  “that game” request must ask “Which game?”; the same reference following an
  explicitly dated game must return cited facts and advance the session revision.
- Container restart loses the committed session. Save the exact request/response
  receipt, then run the replay phase after restarting the owned local containers.
  This phase must reproduce the original response without resetting any state.
- A test silently becomes paid-model verification. Require the local stack's
  mock/deterministic configuration, inspect disabled OpenRouter readiness, and
  reject any response marked `llm_validated`. This is local infrastructure evidence,
  not proof that hosted Redis or the paid-provider release gates passed.
- Deterministic factual delivery is mistaken for infrastructure degradation.
  The current evidence loop marks its cited `factual_fallback` response degraded
  with exactly `Model or budget unavailable.` when model use is disabled. Accept
  only this documented shape; reject other degraded routes, extra warnings,
  missing citations, and dependency failures. Record this limitation in the receipt.
- Verification artifacts overwrite prior evidence or disappear on a failed check.
  Create a new output directory per phase, retain every completed HTTP exchange,
  record failure details and invocation, and save the receipt with mode 0600.
  An unreachable loopback API must exit nonzero and still retain its connection
  failure in `verification.json`. The writer must use builtin `open` for the
  custom permissions opener (`Path.open` does not accept it). If artifact writing
  itself fails, report both that failure and the original verification failure
  without an uncaught exception in cleanup replacing the original diagnosis.
- Repeated probes exhaust the real public chat quota. The initial phase uses six
  analyst requests and replay uses one; retain the normal 10/minute and 100/day
  limits and wait for quota recovery if more checks are needed.

Browser verification should use the actual local web image and its `/api` proxy
without mocked route responses: load the archive, open a game/report, ask a dated
question in `/analyst`, follow up using “that game,” reload, and retain a screenshot
plus request/response evidence. Existing `parity.spec.ts` tests replace API
responses and therefore do not establish container integration.
