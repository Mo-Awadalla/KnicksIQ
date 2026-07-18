# Production database operations resources

## Knowledge

- [PostgreSQL: Transactions](https://www.postgresql.org/docs/current/tutorial-transactions.html)
  Primary documentation for the all-or-nothing guarantee that keeps a release from becoming partially visible. Use for: understanding commit and rollback.
- [Alembic Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
  Official guide to migration environments and revision scripts. Use for: what `alembic upgrade head` changes.
- [Neon: SQLAlchemy connection guide](https://neon.com/docs/guides/sqlalchemy)
  Official guidance for connecting an application to a Neon Postgres database. Use for: connection-string and deployment setup.

## Wisdom (Communities)

- [PostgreSQL Mailing Lists](https://www.postgresql.org/list/)
  Maintainer-led discussion channels. Use for: unusual PostgreSQL operational questions after reproducing the issue.

## Gaps

- A future lesson should cover backups and restore rehearsals for a production release.
