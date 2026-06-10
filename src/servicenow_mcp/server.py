#!/usr/bin/env python3
"""ServiceNow MCP Server — Python implementation (FastMCP).

Transports:
  stdio             (default) — for local Claude / IDE use
  sse               — HTTP Server-Sent Events (legacy clients)
  streamable-http   — recommended for centralized server deployment

Usage:
  servicenow-mcp                          # stdio
  servicenow-mcp --transport sse          # SSE on 0.0.0.0:8000
  servicenow-mcp --transport streamable-http --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool, TextContent

from .servicenow.client import ServiceNowClient
from .servicenow.types import ServiceNowConfig, BasicAuthConfig, OAuthConfig, BearerTokenConfig
from .tools import get_tools, execute_tool
from .utils.cache import build_cache_from_env
from .utils.errors import ServiceNowError
from .utils.logging import logger, audit_log


def _build_config() -> ServiceNowConfig:
    """Build ServiceNowConfig from environment variables."""
    instance_url = os.environ.get("SERVICENOW_INSTANCE_URL", "")
    if not instance_url:
        logger.error("SERVICENOW_INSTANCE_URL is required.")
        sys.exit(1)

    auth_method = os.getenv("SERVICENOW_AUTH_METHOD", "basic")

    basic = None
    oauth = None
    bearer = None

    if auth_method == "passthrough":
        pass
    elif auth_method == "basic":
        basic = BasicAuthConfig(
            username=os.environ.get("SERVICENOW_BASIC_USERNAME", ""),
            password=os.environ.get("SERVICENOW_BASIC_PASSWORD", ""),
        )
    elif auth_method == "bearer":
        bearer = BearerTokenConfig(
            token=os.environ.get("SERVICENOW_BEARER_TOKEN", ""),
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
        bearer=bearer,
        max_retries=int(os.getenv("SERVICENOW_MAX_RETRIES", "3")),
        retry_delay_ms=int(os.getenv("SERVICENOW_RETRY_DELAY_MS", "1000")),
        request_timeout_s=int(os.getenv("SERVICENOW_REQUEST_TIMEOUT_S", "30")),
        cb_failure_threshold=int(os.getenv("SERVICENOW_CB_FAILURE_THRESHOLD", "5")),
        cb_recovery_timeout_s=int(os.getenv("SERVICENOW_CB_RECOVERY_TIMEOUT_S", "30")),
        cb_half_open_max_calls=int(os.getenv("SERVICENOW_CB_HALF_OPEN_MAX_CALLS", "1")),
    )


mcp = FastMCP(
    "servicenow-mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="ServiceNow MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "0.0.0.0"),
        help="Bind host for HTTP transports (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="Bind port for HTTP transports (default: 8000)",
    )
    args = parser.parse_args()

    load_dotenv()

    config = _build_config()
    client = ServiceNowClient(config)
    tools = get_tools()
    cache = build_cache_from_env()

    server = mcp._mcp_server

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {"type": "object", "properties": {}}),
            )
            for t in tools
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
        logger.info(f"Tool called: {name}")
        try:
            result = await execute_tool(client, name, arguments, cache=cache)
            text = result if isinstance(result, str) else json.dumps(result, indent=2, default=str)
            audit_log(name, arguments, "success")
            return [TextContent(type="text", text=text)]
        except ServiceNowError as e:
            logger.error(f"Tool error: {name} — {e}")
            audit_log(name, arguments, "error", str(e))
            return [TextContent(type="text", text=f"Error: {e} (Code: {e.code})")]
        except Exception as e:
            logger.error(f"Unexpected error: {name} — {e}")
            audit_log(name, arguments, "error", str(e))
            return [TextContent(type="text", text=f"Error: {e}")]

    logger.info(f"servicenow-mcp starting [{len(tools)} tools] transport={args.transport}")
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn
        from .utils.auth_middleware import BearerPassthroughMiddleware

        base_app = mcp.sse_app() if args.transport == "sse" else mcp.streamable_http_app()
        app = BearerPassthroughMiddleware(base_app)

        oauth_client_id = os.getenv("SERVICENOW_OAUTH_CLIENT_ID")
        oauth_client_secret = os.getenv("SERVICENOW_OAUTH_CLIENT_SECRET")
        if config.auth_method == "passthrough" and oauth_client_id and oauth_client_secret:
            from .utils.oauth_proxy import OAuthProxyMiddleware
            app = OAuthProxyMiddleware(app, config.instance_url, oauth_client_id, oauth_client_secret)
            logger.info(f"Listening on {args.host}:{args.port} — OAuth login via ServiceNow enabled")
        else:
            logger.info(f"Listening on {args.host}:{args.port} — bearer token forwarding enabled")

        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
