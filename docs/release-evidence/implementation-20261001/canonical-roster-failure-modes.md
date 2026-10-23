# Approved archive player identity failure modes

Written before the HTTP specification and implementation. The local immutable
cohort probe returned duplicated Towns and Bridges ambiguity choices. The raw
approved bundle contains one canonical Karl-Anthony Towns and one Mikal Bridges;
the source of the extra stored identities must be reproduced and corrected.

- Existing seed/older player metadata wins over approved identity fields for
  the same NBA player ID. The loaded release must retain the bundle's exact
  identity, team and descriptive roster fields, without inventing player IDs.
- Updating identities breaks player/stat foreign keys, duplicates records, or
  silently reassigns an old stat to a different NBA player. NBA ID is the join
  identity; do not relabel foreign keys by surname or evaluation answer.
- A repeated bundle import changes row identities, totals or query results.
  Verify import idempotence through real SQL and subsequent HTTP responses.
- A surname is artificially ambiguous because two different NBA IDs carry an
  incorrect shared name. Preserve genuine ambiguity, including different people
  with a real shared surname; only synchronize approved source attributes.
- The fix substitutes gold labels, changes the approved compressed bundle or
  immutable questions, or dispatches a provider during local verification.
- New corpus/source text is incorrectly claimed to preserve prior retrieval,
  provider-quality, load, or release-readiness proofs. Fresh bindings are needed.

HTTP checks load the pinned approved archive through the actual loader into the
normal seeded fixture database, retain the before/after canonical metadata and
requests/responses, and use disposable Redis with model construction denied.
