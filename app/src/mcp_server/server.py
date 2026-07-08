"""MCP context — server factory.

Builds the MCP server (stateless Streamable HTTP) and registers its tools.
Stateless mode keeps the server simple and horizontally scalable on Azure
Container Apps, mirroring the original TypeScript implementation.

Transport settings:
  - json_response=True: Copilot Studio expects plain JSON responses
    (application/json). SSE streaming causes 406 errors when APIM or
    the client does not forward `Accept: text/event-stream`.
  - DNS rebinding protection is DISABLED because the server runs behind
    Azure APIM / Container Apps ingress which performs Host validation
    at the network edge. The SDK default (localhost-only) rejects
    external callers with HTTP 421.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from ..identity.caller_identity import resolve_caller_identity
from ..shared.server_info import SERVER_NAME


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        SERVER_NAME,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )

    @mcp.tool(
        name="test_lgup",
        title="Test LGUP",
        description="A connectivity test tool that returns a fixed confirmation message.",
    )
    async def test_lgup() -> str:
        return "test lgup mcp ok"

    @mcp.tool(
        name="get_current_user",
        title="Get Current User",
        description=(
            "Returns information about the connected user (Copilot Studio caller) "
            "derived from the forwarded identity headers or bearer token."
        ),
    )
    async def get_current_user() -> str:
        request = mcp.get_context().request_context.request
        headers = request.headers if request is not None else {}
        user = resolve_caller_identity(headers)
        if user["authenticated"]:
            return json.dumps(user, indent=2, ensure_ascii=False)
        return (
            "No user identity was forwarded to the MCP server. The endpoint is "
            "currently unauthenticated, so enable authentication on the Container "
            "App / APIM and configure Copilot Studio to forward the user token to "
            "receive caller details."
        )

    return mcp
