# Public beta release checklist

The owner signs this checklist. The selected production domain is
`knicksiq.win`, the feedback form uses Formspree form `xaqrndvp`, and production
AI is allowlisted to `nvidia/nemotron-3-ultra-550b-a55b:free` with zero-data-
retention routing required on every OpenRouter request.

- [ ] Purchase the domain; configure `www`, `api`, and apex redirect; verify DNS and TLS.
- [ ] Complete legal review of NBA/source, Qdrant, OpenRouter, Upstash, Sentry, Render, and Formspree terms.
- [ ] Build the release offline; verify its SHA-256; achieve 100% game/report/reconciliation coverage.
- [ ] Manually review and mark exactly one immutable postgame report per game.
- [ ] Pass 100% canonical numeric/entity facts, 95% paraphrase/citation evaluation, and 95% semantic Recall@5.
- [ ] Pass Ruff, Pyright, pytest, Postgres migrations, pnpm lint/format/build, browser tests, Playwright, CodeQL, secret scan, and critical container scan.
- [ ] Pass k6 at 10 concurrent analysts: archive p95 <1s, analyst p95 <4s, errors <1%.
- [ ] Record zero serious/critical axe findings; perform manual keyboard and current VoiceOver/NVDA smoke tests.
- [ ] Verify the OpenRouter zero-retention model allowlist, $8 app cutoff, and $9 provider guardrail.
- [ ] Verify Sentry scrubbing, email alerts, uptime monitor, no replay, and no prompt/IP capture.
- [ ] Verify Upstash failure, Qdrant failure, and OpenRouter failure preserve deterministic factual answers.
- [ ] Restore Postgres and rebuild Qdrant from the immutable bundle inside four hours.
- [ ] Stage the release, deploy the immutable image manually, activate data/index aliases, and run synthetic smoke tests.
- [ ] Verify dashboards, alerts, backup, rollback, privacy/terms/sources, feedback retention disclosure, and private security address.
- [ ] Owner records go/no-go decision and incident contact.

## Local preflight evidence — 2026-07-14

This evidence does not replace owner sign-off or production/staging verification.

- Candidate validation passed for 101 games. The candidate bundle SHA-256 is
  `55d6aa90c206f3b3386cb4b8d056fb84ae51f5482a86e8c2ee920c72378c385c`.
- Reconciliation covers 46,500 events, 816 period scores, 202 team box-score
  rows, 2,748 player box-score rows, and 101 report drafts.
- Ruff, Pyright, 142 Python tests, clean and populated-schema Alembic upgrades,
  transactional loader integration, frontend lint/format/build, 42 browser
  tests, and Playwright passed.
- Automated axe checks reported zero serious or critical findings on the public
  archive. Manual keyboard and current VoiceOver/NVDA checks remain required.
- Qdrant contains 11,334 possession chunks and the expected 101 game, 2,950
  box-score, and 101 report points behind versioned aliases.
- Explicit regression tests prove Qdrant, Redis, and OpenRouter failures preserve
  deterministic factual answers or degrade safely.
- A disposable full-candidate k6 rehearsal at 10 concurrent users recorded 0%
  errors, archive p95 17.7 ms, and analyst p95 271 ms. Staging/production load
  verification remains required.
- Gitleaks found no current or historical unignored secrets. Trivy found zero
  critical vulnerabilities in both rebuilt API and web images.
- Strict bundle construction still rejects the candidate because zero of 101
  report hashes have owner approval. No production bundle was created or
  activated.
