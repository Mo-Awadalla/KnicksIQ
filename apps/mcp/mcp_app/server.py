"""MCP server entry point.

Exposes the basketball tools via the official MCP Python SDK.
Two transports are supported:
  - stdio (`python -m mcp_app.server`): for local MCP clients like
    Claude Desktop
  - HTTP+SSE (`python -m mcp_app.server --sse`): for browser/curl
    clients and the dashboard's tool-trace viewer.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from mcp.server import FastMCP

from mcp_app.core.config import get_settings
from mcp_app.tools import TOOLS

logger = logging.getLogger("knicksiq.mcp")


def _build_server() -> FastMCP:
    settings = get_settings()
    server = FastMCP(settings.server_name)

    @server.tool()
    async def get_games(
        season: str | None = None,
        team_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return await TOOLS["knicks.get_games"](season, team_id, limit)

    @server.tool()
    async def get_game(game_id: int) -> dict[str, Any] | None:
        return await TOOLS["knicks.get_game"](game_id)

    @server.tool()
    async def get_box_score(game_id: int) -> dict[str, Any]:
        return await TOOLS["knicks.get_box_score"](game_id)

    @server.tool()
    async def get_play_by_play(game_id: int, period: int | None = None) -> list[dict[str, Any]]:
        return await TOOLS["knicks.get_play_by_play"](game_id, period)

    @server.tool()
    async def find_scoring_runs(game_id: int, team_id: str | None = None) -> list[dict[str, Any]]:
        return await TOOLS["knicks.find_scoring_runs"](game_id, team_id)

    @server.tool()
    async def find_bad_stretches(game_id: int) -> list[dict[str, Any]]:
        return await TOOLS["knicks.find_bad_stretches"](game_id)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="KnicksIQ MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse"),
        default="stdio",
        help="Transport to use. 'stdio' for Claude Desktop, 'sse' for HTTP.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    server = _build_server()
    if args.transport == "stdio":
        logger.info("knicksiq.mcp.starting transport=stdio")
        server.run(transport="stdio")
    else:
        settings = get_settings()
        logger.info(
            "knicksiq.mcp.starting transport=sse host=%s port=%d",
            settings.sse_host,
            settings.sse_port,
        )
        server.settings.host = settings.sse_host
        server.settings.port = settings.sse_port
        server.run(transport="sse")


if __name__ == "__main__":
    main()
