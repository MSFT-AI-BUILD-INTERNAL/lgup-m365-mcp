import express, { type Request, type Response } from "express";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

const SERVER_NAME = "hanik-mcp-server";
const SERVER_VERSION = "1.0.0";

// Port is configurable so the Bicep-deployed Container App can inject containerPort (default 8080).
const PORT = Number(process.env.PORT ?? 8080);

/**
 * Decode the payload (claims) of a JWT without verifying its signature.
 * NOTE: This only reads claims for display. For trust decisions the token
 * signature/audience/issuer MUST be validated (e.g. via Entra ID JWKS).
 */
function decodeJwtClaims(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length < 2) {
    return null;
  }
  try {
    const payload = Buffer.from(parts[1], "base64url").toString("utf8");
    return JSON.parse(payload) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Resolve the calling user's identity from the incoming request.
 * Supports two common patterns when fronted by Copilot Studio / Azure auth:
 *  1. Azure Container Apps "Easy Auth" injected headers (x-ms-client-principal*).
 *  2. A forwarded Entra ID bearer token in the Authorization header.
 */
function resolveCurrentUser(req: Request): Record<string, unknown> {
  const headers = req.headers;

  // 1) Easy Auth simple headers.
  const principalName = headers["x-ms-client-principal-name"];
  const principalId = headers["x-ms-client-principal-id"];
  const principalIdp = headers["x-ms-client-principal-idp"];

  // 1b) Easy Auth full base64-encoded principal (claims array).
  let easyAuthClaims: Record<string, unknown> | null = null;
  const encodedPrincipal = headers["x-ms-client-principal"];
  if (typeof encodedPrincipal === "string") {
    try {
      easyAuthClaims = JSON.parse(
        Buffer.from(encodedPrincipal, "base64").toString("utf8")
      ) as Record<string, unknown>;
    } catch {
      easyAuthClaims = null;
    }
  }

  // 2) Bearer token claims.
  let tokenClaims: Record<string, unknown> | null = null;
  const authHeader = headers["authorization"];
  if (typeof authHeader === "string" && authHeader.toLowerCase().startsWith("bearer ")) {
    tokenClaims = decodeJwtClaims(authHeader.slice(7).trim());
  }

  const claims = tokenClaims ?? {};
  const displayName =
    (typeof principalName === "string" ? principalName : undefined) ??
    (claims.name as string | undefined) ??
    (claims.preferred_username as string | undefined) ??
    (claims.upn as string | undefined);
  const userId =
    (typeof principalId === "string" ? principalId : undefined) ??
    (claims.oid as string | undefined) ??
    (claims.sub as string | undefined);

  const authenticated = Boolean(displayName || userId || easyAuthClaims);

  return {
    authenticated,
    displayName: displayName ?? null,
    userPrincipalName:
      (claims.preferred_username as string | undefined) ??
      (claims.upn as string | undefined) ??
      (typeof principalName === "string" ? principalName : null),
    email: (claims.email as string | undefined) ?? null,
    objectId: userId ?? null,
    tenantId: (claims.tid as string | undefined) ?? null,
    identityProvider: typeof principalIdp === "string" ? principalIdp : null,
    scopes:
      (claims.scp as string | undefined) ??
      (claims.roles as string[] | undefined) ??
      null,
  };
}

/**
 * Build a fresh MCP server instance per request (stateless Streamable HTTP).
 * Stateless mode keeps the server simple and horizontally scalable on Azure Container Apps.
 */
function createMcpServer(req: Request): McpServer {
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
      const user = resolveCurrentUser(req);
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

const app = express();
app.use(express.json());

// Liveness/readiness probe endpoint for Azure Container Apps.
app.get("/health", (_req: Request, res: Response) => {
  res.status(200).json({ status: "ok", server: SERVER_NAME, version: SERVER_VERSION });
});

// Streamable HTTP MCP endpoint (stateless: a new server + transport per request).
app.post("/mcp", async (req: Request, res: Response) => {
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

// Stateless mode does not support server-initiated streams or session termination.
const methodNotAllowed = (_req: Request, res: Response) => {
  res.status(405).json({
    jsonrpc: "2.0",
    error: { code: -32000, message: "Method not allowed." },
    id: null,
  });
};
app.get("/mcp", methodNotAllowed);
app.delete("/mcp", methodNotAllowed);

app.listen(PORT, () => {
  console.log(`${SERVER_NAME} v${SERVER_VERSION} listening on port ${PORT} (POST /mcp)`);
});
