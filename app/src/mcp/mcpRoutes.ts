import type { Express, Request, Response } from "express";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { requireScope } from "../identity/scopeGuard.js";
import { resolveCallerIdentity } from "../identity/CallerIdentity.js";
import { createMcpServer } from "./mcpServer.js";

/**
 * MCP context — HTTP endpoints.
 *
 * Streamable HTTP MCP endpoint (stateless: a new server + transport per
 * request). Stateless mode does not support server-initiated streams or session
 * termination, so GET/DELETE are explicitly rejected.
 */
export function registerMcpRoutes(app: Express): void {
  app.post("/mcp", async (req: Request, res: Response) => {
    if (!requireScope(req, res)) return;

    const user = resolveCallerIdentity(req);
    console.log("[MCP] Incoming request from:", JSON.stringify({
      displayName: user.displayName,
      userPrincipalName: user.userPrincipalName,
      objectId: user.objectId,
      tenantId: user.tenantId,
      scopes: user.scopes,
      authenticated: user.authenticated,
    }));

    const server = createMcpServer(req);
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
    });

    res.on("close", () => {
      void transport.close();
      void server.close();
    });

    try {
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (error) {
      console.error("Error handling MCP request:", error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: "2.0",
          error: { code: -32603, message: "Internal server error" },
          id: null,
        });
      }
    }
  });

  const methodNotAllowed = (_req: Request, res: Response) => {
    res.status(405).json({
      jsonrpc: "2.0",
      error: { code: -32000, message: "Method not allowed." },
      id: null,
    });
  };
  app.get("/mcp", methodNotAllowed);
  app.delete("/mcp", methodNotAllowed);
}
