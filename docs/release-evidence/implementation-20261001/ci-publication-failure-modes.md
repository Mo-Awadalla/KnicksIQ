# Publication and portable HTTP checks

Before adding a portable fixture, the checks can fail because they reference a
private absolute Mac path absent on GitHub Actions. Publishing the private
approved bundle or skipping the new HTTP checks would not solve portability
within the confirmed scope.

Use an explicitly synthetic, deterministic fixture with its own version, hash,
source labels and generated report text. It must exercise all existing HTTP
assertions: tied games, tied Boston runs, nine-game all-phase Atlanta population,
roster synchronization, player metrics, DNP windows and before/after populations.
Keep source totals, player/team/period reconciliation and event order consistent.
Its numbers are fabricated test data, not actual basketball facts or approved
evaluation labels. The original approved archive stays private and remains an
explicit opt-in using `KNICKSIQ_APPROVED_BUNDLE`; retain its exact existing SHA.

CI must execute the complete checks with disposable SQL/Redis, retain JUnit and
HTTP receipts, and continue the existing PostgreSQL, frontend, container and
security jobs. Failed runs are retained. A passing CI run does not authorize
production launch or resolve the remaining source/gold/dependency gates.
