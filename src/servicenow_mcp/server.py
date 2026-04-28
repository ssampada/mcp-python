#!/usr/bin/env python3
"""ServiceNow MCP Server — Python implementation."""
from __future__ import annotations

import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .servicenow.client import ServiceNowClient
from .servicenow.types import ServiceNowConfig, BasicAuthConfig, OAuthConfig
from .tools import get_tools, execute_tool
from .utils.errors import ServiceNowError
from .utils.logging import logger


def _build_config() -> ServiceNowConfig:
    """Build ServiceNowConfig from environment variables."""
    instance_url = os.environ.get("SERVICENOW_INSTANCE_URL", "")
    if not instance_url:
        logger.error("SERVICENOW_INSTANCE_URL is required.")
        sys.exit(1)

    auth_method = os.getenv("SERVICENOW_AUTH_METHOD", "basic")

    basic = None
    oauth = None

    if auth_method == "basic":
        basic = BasicAuthConfig(
            username=os.environ.get("SERVICENOW_BASIC_USERNAME", ""),
            password=os.environ.get("SERVICENOW_BASIC_PASSWORD", ""),
        )
    else:
        oauth = OAuthConfig(
            client_id=os.environ.get("SERVICENOW_OAUTH_CLIENT_ID", ""),
            client_secret=os.environ.get("SERVICENOW_OAUTH_CLIENT_SECRET", ""),
            username=os.environ.get("SERVICENOW_OAUTH_USERNAME", ""),
            password=os.environ.get("SERVICENOW_OAUTH_PASSWORD", ""),
        )

    return ServiceNowConfig(
        instance_url=instance_url,
        auth_method=auth_method,
        basic=basic,
        oauth=oauth,
    )


def main() -> None:
    load_dotenv()

    app = Server("servicenow-mcp")
    config = _build_config()
    client = ServiceNowClient(config)
    tools = get_tools()

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {"type": "object", "properties": {}}),
            )
            for t in tools
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        logger.info(f"Tool called: {name}")
        try:
            result = await execute_tool(client, name, arguments)
            text = result if isinstance(result, str) else json.dumps(result, indent=2, default=str)
            return [TextContent(type="text", text=text)]
        except ServiceNowError as e:
            logger.error(f"Tool error: {name} — {e}")
            return [TextContent(type="text", text=f"Error: {e} (Code: {e.code})")]
        except Exception as e:
            logger.error(f"Unexpected error: {name} — {e}")
            return [TextContent(type="text", text=f"Error: {e}")]

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    logger.info(f"servicenow-mcp Python server starting [{len(tools)} tools]")
    asyncio.run(run())


if __name__ == "__main__":
    main()
