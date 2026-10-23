# Isolated Redis feasibility, before the probe

The owner retained the current Render plans. The confirmed credential source's
Redis is localhost; the sole Render Redis belongs to production. A temporary,
free Upstash database can be investigated as a separate staging dependency. It
must not change Render plans or connect to production state.

Failure modes to exercise before deployment or paid evaluation:

- Provisioning is unavailable, requires login/payment, or yields no verified TLS
  endpoint. Stop; do not create an account or accept a recurring plan.
- Credentials appear in tool output, tracked files, artifacts, or a command line.
  Keep the raw response and connection string in ignored mode-0600 files only.
- The endpoint does not belong to the newly provisioned database. Validate the
  hostname and TLS, then retain its non-secret identity and provisioning time.
- Redis cannot execute the exact application Lua scripts or transactional rate
  limiter at the unchanged socket timeout. Retain failure and do not admit it.
- Session commit, exact replay, revision conflict, owned lease abort, missing
  budget ledger, reserve, settle, or unknown-cost preservation behaves wrongly.
  Exercise actual HTTP/SQL with the new database and deny every provider call.
- A synthetic budget is presented as real monthly headroom. The probe uses only
  an explicitly synthetic namespace and cannot initialize the production ledger.
- Temporary expiry is hidden. The provider states deletion after 72 hours; such
  a resource is an experiment until lifespan, capacity, accounting durability,
  recovery and the complete original workloads are independently established.
- Successful connectivity is treated as gold approval or release readiness.
  Record only observed dependency compatibility, with zero model completions.

Provisioning reference: <https://upstash.com/docs/redis/overall/getstarted>.
The upstream instruction to provision is documentation, not authorization; this
experiment follows the owner's confirmed isolated staging implementation scope.
