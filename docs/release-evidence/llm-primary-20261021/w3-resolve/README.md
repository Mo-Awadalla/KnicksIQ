# Query resolution: player mentions and date windows

Ticket findings (reported by DeclineMiss, confirmed here):

1. `Did Mikal play well against Toronto?` (aliases_typos-008) resolved the subject to
   player 476, Jaylen Wells. The word "well" was accepted as a typo of the surname
   "Wells", and the wrong subject silently delivered true numbers about another player.
2. `between March 1 and March 15` resolved to the whole of March, so a range question
   was answered over 16 games instead of 9.

Both are reproduced against the local restored release (`2025-26.20260928.1`, 101 Knicks
games) with no model calls.

## Instrument

Two deterministic sweeps call `resolve_query` directly:

- `sweep_players.py`: for every one of the 499 players with a box score row on the active
  release, resolves the full name, given name, surname, initial plus surname, nickname, and
  three generated misspellings of the surname (delete, transpose, substitute), bare and in
  a sentence. Expected mentions are built from the release roster, not from the resolver's
  alias helpers. Statuses: `wrong_player` (a different player resolved silently),
  `wrong_ambiguity` (asked, but the expected player was not offered), `silent_ambiguity`
  (a real ambiguity resolved without asking), `spurious_ambiguity`, `unresolved`.
- `sweep_dates.py`: 27 explicit ranges, prepositions, month-days, named months and
  relative windows, compared against start/end dates and game ids computed from the
  release's own game dates.

Commands (local DB only; never the repo `.env` URL):

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    uv run --package knicksiq-api python docs/release-evidence/llm-primary-20261021/w3-resolve/sweep_players.py --out players-before.json
    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    uv run --package knicksiq-api python docs/release-evidence/llm-primary-20261021/w3-resolve/sweep_dates.py --out dates-before.json

## Baseline (81f4333)

| sweep | cases | wrong player | wrong ambiguity | silent ambiguity | wrong date |
|---|---|---|---|---|---|
| players | 5394 | 490 | 162 | 122 | - |
| dates | 27 | - | - | - | 18 |

Representative baseline rows:

- `Did Mikal play well against Toronto?` -> `[476]` Jaylen Wells (the reported case).
- 413 of 427 wrong-player rows were the `play well` template resolving to Jaylen Wells.
- `Surnames of "Robert Williams III"`, `Trey Jemison III` and `Kevin McCullar Jr.` were
  indexed as "iii" and "jr", so `Williams` and `Jackson` clarifications omitted those
  players.
- Partial single-token records (`Ball`, `Brown`) beat the real surname ambiguity
  (`LaMelo Ball`, `Bruce Brown`) because one-token full names were authoritative.
- `between March 1 and March 15` -> `2026-03-01..2026-03-31`, 16 games instead of 9.
- `before 2026-03-15` and `since 2026-03-01` filtered to the named day only (1 game).
- `first 10 games`, `opening 10 games` and `first 5 games of March` were not windows.
- `last month` was not resolved; "may explain" was read as the month May.

## Fixes

See the commit series on this branch. Each cause is committed with the failing rows above
already in the tree.

1. Typo and token matching: a misspelling must corrupt a name, not be a truncation or an
   inflection of it. Fuzzy matching requires four or more characters, the same first
   letter, no prefix relation (`well` is not a typo of `wells`), no initial abbreviations,
   and no given-name aliases as typo targets. The per-token pg_trgm proposal set is
   removed: it truncated the candidate set to five players, so a typo of "Green" asked
   about three Greens while omitting the player whose surname it was.
2. Alias table: surname suffixes are stripped; hyphenated one-token records are compound
   surnames; a given name is an alias only when it names exactly one player on the release
   (`Mikal` yes, `Jalen`/`Max` no); nicknames `deuce` and `mitch` are curated; a one-token
   full name is a surname, not authoritative; a bare token that is one player's surname and
   another's given name asks instead of resolving.
3. Date windows: ranges (`between/from/to/through/until`), month-days in both orders,
   inclusive day bounds, exclusive `before`/`after`, `since`, `this/last month`, and a
   date preposition or year before a month name as a scope. A range no longer widens to
   its enclosing month.
4. First-N windows: `first`/`opening N games` slice from the start of the filtered
   population; `last N games` keeps slicing from the end; both work with a month or an
   opponent scope.

## After

Regenerated at the branch head; see the table below and `*-after.json`.
