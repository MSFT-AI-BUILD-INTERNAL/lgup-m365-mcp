import type { Express, Request, Response } from "express";
import { MSAL_BROWSER_PATH } from "../shared/serverInfo.js";
import { loadEntraSettings } from "../shared/entraSettings.js";
import { renderAuthTestUiPage } from "./authTestUiPage.js";
import { renderDrmTestUiPage } from "./drmTestUiPage.js";

/**
 * Presentation layer — browser-facing test UIs.
 *
 * Serves the Entra login + MCP API test page, the login-gated DRM decrypt page,
 * a small config endpoint, and the MSAL browser bundle (locally, to avoid an
 * external CDN dependency).
 */
export function registerUiRoutes(app: Express): void {
  // Serve the MSAL browser library locally so the login UIs work without an external CDN.
  app.get("/vendor/msal-browser.min.js", (_req: Request, res: Response) => {
    res.setHeader("Content-Type", "application/javascript; charset=utf-8");
    res.sendFile(MSAL_BROWSER_PATH);
  });

  app.get("/auth-ui/config", (_req: Request, res: Response) => {
    const entra = loadEntraSettings();
    res.json({
      tenantId: entra.tenantId,
      clientId: entra.clientId,
      scope: entra.clientId ? entra.delegatedScopeUri : "",
    });
  });

  app.get("/auth-ui", (_req: Request, res: Response) => {
    const entra = loadEntraSettings();
    if (!entra.isConfigured) {
      res.status(503).send(
        "AUTH_CLIENT_ID / AUTH_TENANT_ID environment variables are required for Entra ID test UI."
      );
      return;
    }

    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.status(200).send(
      renderAuthTestUiPage({
        tenantId: entra.tenantId,
        clientId: entra.clientId,
        scope: entra.requiredScope,
      })
    );
  });

  // DRM / MIP decrypt test UI (Entra login gate shown first).
  app.get("/drm-ui", (_req: Request, res: Response) => {
    const entra = loadEntraSettings();
    if (!entra.isConfigured) {
      res.status(503).send(
        "AUTH_CLIENT_ID / AUTH_TENANT_ID environment variables are required for the DRM test UI."
      );
      return;
    }

    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.status(200).send(
      renderDrmTestUiPage({
        tenantId: entra.tenantId,
        clientId: entra.clientId,
        scope: entra.requiredScope,
      })
    );
  });
}
