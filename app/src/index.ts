import express, { type Request, type Response } from "express";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

const SERVER_NAME = "hanik-mcp-server";
const SERVER_VERSION = "1.0.0";

// Port is configurable so the Bicep-deployed Container App can inject containerPort (default 8080).
const PORT = Number(process.env.PORT ?? 8080);

const REQUIRED_SCOPE = "access_as_user";

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

// RFC 9728 — OAuth Protected Resource Metadata.
// Advertises this server's auth requirements so OAuth-aware MCP clients can auto-discover them.
app.get("/.well-known/oauth-protected-resource", (req: Request, res: Response) => {
  const authClientId = process.env.AUTH_CLIENT_ID;
  const authTenantId = process.env.AUTH_TENANT_ID;

  if (!authClientId || !authTenantId) {
    res.status(503).json({
      error: "OAuth metadata not configured. AUTH_CLIENT_ID and AUTH_TENANT_ID environment variables are required.",
    });
    return;
  }

  // Point to our own server as the authorization server metadata host.
  const baseUrl = `${req.protocol}://${req.get("host")}`;

  res.json({
    resource: `api://${authClientId}`,
    authorization_servers: [baseUrl],
    scopes_supported: ["access_as_user"],
    bearer_methods_supported: ["header"],
  });
});

// RFC 8414 — OAuth Authorization Server Metadata.
// Advertises Entra ID endpoints so OAuth clients can discover token/authorize URLs.
app.get("/.well-known/oauth-authorization-server", (req: Request, res: Response) => {
  const authClientId = process.env.AUTH_CLIENT_ID;
  const authTenantId = process.env.AUTH_TENANT_ID;

  if (!authClientId || !authTenantId) {
    res.status(503).json({
      error: "OAuth metadata not configured. AUTH_CLIENT_ID and AUTH_TENANT_ID environment variables are required.",
    });
    return;
  }

  const baseUrl = `${req.protocol}://${req.get("host")}`;
  const entraBase = `https://login.microsoftonline.com/${authTenantId}/v2.0`;

  res.json({
    issuer: entraBase,
    authorization_endpoint: `https://login.microsoftonline.com/${authTenantId}/oauth2/v2.0/authorize`,
    token_endpoint: `https://login.microsoftonline.com/${authTenantId}/oauth2/v2.0/token`,
    jwks_uri: `https://login.microsoftonline.com/${authTenantId}/discovery/v2.0/keys`,
    scopes_supported: ["openid", "profile", "email", "offline_access", `api://${authClientId}/access_as_user`],
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code", "client_credentials"],
    token_endpoint_auth_methods_supported: ["client_secret_post", "client_secret_basic"],
    code_challenge_methods_supported: ["S256"],
  });
});

// Streamable HTTP MCP endpoint (stateless: a new server + transport per request).
/**
 * Validates that the incoming request carries a token with the required scope.
 * APIM performs primary JWT signature/audience/issuer validation; this is a
 * defence-in-depth check ensuring the correct delegated permission is present.
 */
function requireScope(req: Request, res: Response): boolean {
  const authHeader = req.headers["authorization"];
  if (typeof authHeader !== "string" || !authHeader.toLowerCase().startsWith("bearer ")) {
    const authClientId = process.env.AUTH_CLIENT_ID ?? "";
    const authTenantId = process.env.AUTH_TENANT_ID ?? "";
    res.setHeader(
      "WWW-Authenticate",
      `Bearer realm="api://${authClientId}", authorization_uri="https://login.microsoftonline.com/${authTenantId}/oauth2/v2.0/authorize"`
    );
    res.status(401).json({
      jsonrpc: "2.0",
      error: { code: -32000, message: "Unauthorized. Bearer token required." },
      id: null,
    });
    return false;
  }

  const claims = decodeJwtClaims(authHeader.slice(7).trim());
  if (claims) {
    const scp = typeof claims.scp === "string" ? claims.scp.split(" ") : [];
    const roles = Array.isArray(claims.roles) ? (claims.roles as string[]) : [];
    const allScopes = [...scp, ...roles];
    if (!allScopes.includes(REQUIRED_SCOPE)) {
      res.status(403).json({
        jsonrpc: "2.0",
        error: {
          code: -32000,
          message: `Forbidden. Token must include the '${REQUIRED_SCOPE}' scope.`,
        },
        id: null,
      });
      return false;
    }
  }

  return true;
}

// Streamable HTTP MCP endpoint (stateless: a new server + transport per request).
app.post("/mcp", async (req: Request, res: Response) => {
  if (!requireScope(req, res)) return;

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
