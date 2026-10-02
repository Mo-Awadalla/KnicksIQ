# Verification spending direction, before implementation

The owner's retained `confirmed-spending-direction.json` supersedes historical
testing dollar caps. It does not supersede request ceilings, price bounds,
normal monthly accounting, isolated resources, unknown reservations or stop
state. Production configuration must stay unchanged.

Failure modes:

- A caller can supply a boolean, altered statement, or unrelated approval to
  remove caps. Bind the exact retained owner-direction bytes by SHA256.
- Applying the direction resets counts, rewrites costs, releases pending calls,
  unstops a failed journal or changes shadow membership. Preserve all rows and
  fail before mutation on stopped or in-flight journals.
- The stage dollar cap is removed while the historical combined dollar cap
  still rejects the authorized HTTP run. Exercise nested actual analyst calls
  through the counted transport above both old limits, with synthetic charges.
- The direction disappears on reopen. Retain its digest in the durable journal
  and expose it in cumulative snapshots.
- An unknown response, cancellation, or over-bound charge can continue after
  caps are lifted. Keep existing conservative reservations and stop semantics.
- Smoke, primary, or actual-selected shadow request ceilings are lifted. Exercise
  concurrent counted requests at the fixed shadow ceiling; retain rejected calls.
- Application monthly cutoff or ledger behavior is changed. Run through actual
  HTTP/SQL/disposable Redis and assert the existing $2 setting and settled ledger.

The new HTTP specifications must precede code. They use synthetic provider
responses and retain repeatable artifacts; they are not a live admission or an
audited resume of the missing original stopped smoke journal.
