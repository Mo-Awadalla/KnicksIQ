# Independent archive source verification failures

Written before the CLI end-to-end specification and verifier implementation.
The verifier reads the pinned approved gzip, exported source units and alias
policy AST independently of the runtime unit builder. It has no network, DB,
provider, credential, gold-freeze or approval path.

- An altered approved bundle or changed release/content manifest is accepted.
- A unit identity does not bind its exact full payload and text.
- A source ID is listed without its complete canonical facts in rows and text.
- A partial opponent population is called complete, or wrong scores, dates,
  phases, teams, result counts or source hashes are accepted.
- SQL game/player IDs are duplicated or mapped inconsistently across units.
- An identity uses the wrong NBA player, team or descriptive roster metadata.
- An unsupported alias is added, or a curated alias is represented as a raw
  canonical roster field. The exact policy source hash is retained.
- Extra prose or unrecognized payload fields smuggle unsupported claims into
  an otherwise correctly signed source unit.
- A missing/duplicate opponent or player unit passes full archive verification.
- A retrieved unit differs from the independently checked export, or its
  release, text, scalar game ID or source identity is wrong.
- A fabricated or non-ranked receipt is described as actual top-five proof.
- Receipt integrity is promoted to semantic relevance, approved gold or launch.
- Failed checks overwrite successful evidence or silently omit failure artifacts.
- Verification opens a socket or changes source inputs.

## Verified comparison import and retrieval failures

Specified before the SQL/import and HTTP E2E implementations:

- A source import accepts unpinned bundle, trajectory, source-review or comparison
  bytes; mismatching version, population, source identities or recipe are accepted.
- Comparison values/boundaries differ from independent recomputation over the
  pinned, primary-action-verified trajectories.
- The target SQL release differs from the approved bundle, or any game, event,
  actor, clock, score, source hash or period row differs from its source projection.
  Imported comparisons must bind that full SQL snapshot, not a representative row.
- Import changes the canonical archive, active release, reports, player statistics,
  provider budgets or old accounting. Comparison proof is stored separately.
- A changed source silently overwrites an immutable import, or an identical repeat
  changes its identity. Failed imports leave no eligible partial source record.
- Missing proof or a changed SQL snapshot admits scoring comparison units.
- A source unit silently reduces its compared population, omits tied extrema/run
  boundaries, introduces a metric default/causal claim, or inflates canonical refs
  beyond facts physically represented in the full unit.
- An aggregate uses a representative scalar game ID, leaks across selected release,
  game/player/period scope, or serves different facts under one source identity.
- The index export and actual ranked HTTP receipt differ, or an independently
  recomputed mapping manufactures top-five membership.
- Dense indexing sends the complete comparison proof JSON as an embedding input,
  exceeding model context limits. A compact, supported descriptor must be bound
  separately while the physical payload and source receipts remain complete.
- Lexical ranking counts repeated proof/schema keys rather than the supported
  source subject, allowing an unrelated metric family to dominate a question.
- A unique adjacent-letter transposition in an otherwise unmatched subject word
  loses the source match. Repair must use actual eligible source vocabulary,
  not case IDs, hand-authored ranked receipts or an inferred metric default.
- The original 120 questions/contexts, 50 semantic members, seven settled sets,
  nine Atlanta targets, approved clarifications or scorer thresholds change.
- HTTP/import verification constructs a provider, requests dense network inference,
  reserves paid calls, resets a ledger, or approves/freezes gold.
