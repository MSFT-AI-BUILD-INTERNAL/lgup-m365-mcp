import express, { type Request, type Response } from "express";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

const SERVER_NAME = "hanik-mcp-server";
const SERVER_VERSION = "1.0.0";

// Port is configurable so the Bicep-deployed Container App can inject containerPort (default 8080).
const PORT = Number(process.env.PORT ?? 8080);

/**
 * Build a fresh MCP server instance per request (stateless Streamable HTTP).
 * Stateless mode keeps the server simple and horizontally scalable on Azure Container Apps.
 */
function createMcpServer(): McpServer {
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
  const server = createMcpServer();
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
