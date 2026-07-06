import type { Request } from "express";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { SERVER_NAME, SERVER_VERSION } from "../shared/serverInfo.js";
import { resolveCallerIdentity } from "../identity/CallerIdentity.js";

/**
 * MCP context — server factory.
 *
 * Builds a fresh MCP server instance per request (stateless Streamable HTTP).
 * Stateless mode keeps the server simple and horizontally scalable on Azure
 * Container Apps.
 */
export function createMcpServer(req: Request): McpServer {
  const server = new McpServer({
    name: SERVER_NAME,
    version: SERVER_VERSION,
  });

  // Single test tool: always replies with "test hanik mcp ok".
  server.registerTool(
    "test_hanik",
    {
      title: "Test Hanik",
      description: "A connectivity test tool that returns a fixed confirmation message.",
      inputSchema: {},
    },
    async () => ({
      content: [
        {
          type: "text",
          text: "test hanik mcp ok",
        },
      ],
    })
  );

  // Returns information about the user that is calling this MCP server
  // (for example, the signed-in Copilot Studio user, when identity is forwarded).
  server.registerTool(
    "get_current_user",
    {
      title: "Get Current User",
      description:
        "Returns information about the connected user (Copilot Studio caller) derived from the forwarded identity headers or bearer token.",
      inputSchema: {},
    },
    async () => {
      const user = resolveCallerIdentity(req);
      const text = user.authenticated
        ? JSON.stringify(user, null, 2)
        : "No user identity was forwarded to the MCP server. The endpoint is currently unauthenticated, so enable authentication on the Container App / APIM and configure Copilot Studio to forward the user token to receive caller details.";
      return {
        content: [
          {
            type: "text",
            text,
          },
        ],
      };
    }
  );

  return server;
}
