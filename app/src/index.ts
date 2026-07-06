import express from "express";
import { PORT, SERVER_NAME, SERVER_VERSION } from "./shared/serverInfo.js";
import { registerUiRoutes } from "./presentation/uiRoutes.js";
import { registerDrmRoutes } from "./drm/drmRoutes.js";
import { registerOAuthMetadataRoutes } from "./oauth/oauthMetadataRoutes.js";
import { registerMcpRoutes } from "./mcp/mcpRoutes.js";

/**
 * Composition root.
 *
 * Wires the bounded contexts together behind a single Express app:
 *  - presentation  : browser test UIs (/auth-ui, /drm-ui, /vendor, /auth-ui/config)
 *  - drm           : DRM/MIP decrypt proxy (/drm/decrypt)
 *  - oauth         : OAuth discovery metadata (/.well-known/*)
 *  - mcp           : Streamable HTTP MCP endpoint (/mcp)
 */
const app = express();
app.use(express.json());

registerUiRoutes(app);
registerDrmRoutes(app);
registerOAuthMetadataRoutes(app);
registerMcpRoutes(app);

// Liveness/readiness probe endpoint for Azure Container Apps.
app.get("/health", (_req, res) => {
  res.status(200).json({ status: "ok", server: SERVER_NAME, version: SERVER_VERSION });
});

app.listen(PORT, () => {
  console.log(`${SERVER_NAME} v${SERVER_VERSION} listening on port ${PORT} (POST /mcp)`);
});
