import { createRequire } from "node:module";

/**
 * Shared kernel: process-wide server identity and runtime configuration.
 * Kept intentionally small and stable so every bounded context can depend on it.
 */
export const SERVER_NAME = "lgup-ax-mcp-server";
export const SERVER_VERSION = "1.0.0";

// Port is configurable so the Bicep-deployed Container App can inject containerPort (default 8080).
export const PORT = Number(process.env.PORT ?? 8080);

// Resolve the MSAL browser UMD bundle so the test UIs can load it locally
// (avoids depending on an external CDN that may be blocked on corporate networks).
const _require = createRequire(import.meta.url);
export const MSAL_BROWSER_PATH = _require.resolve(
  "@azure/msal-browser/lib/msal-browser.min.js"
);
