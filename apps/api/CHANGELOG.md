# API changelog

## Unreleased

### Fixed

- Treat per-game player rates as aggregates across the scoped appearances, not as requests for one game.
- Resolve Christmas Day against the active archive season and keep conversational game references pinned to unique, recent identities in the active release.
- Carry verified threshold-match game identities into all-games outcome checks without filtering the original set to wins, and recompute leader facts from the resolved game's rows.
