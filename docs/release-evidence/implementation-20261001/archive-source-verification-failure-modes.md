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
