"""Async database engine for the MCP server.

Shares the API's models and connection. The MCP server is a
read-only consumer of the same Postgres (or SQLite) the API writes to.
"""

from __future__ import annotations

from app.core.db import AsyncSessionLocal, engine  # noqa: F401

__all__ = ["engine", "AsyncSessionLocal"]
