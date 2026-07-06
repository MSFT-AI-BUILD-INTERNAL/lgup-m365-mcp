import type { Express, Request, Response } from "express";
import { loadEntraSettings } from "../shared/entraSettings.js";

/**
 * OAuth discovery context — advertises this server's auth requirements and the
 * backing Entra ID endpoints so OAuth-aware MCP clients can auto-discover them.
 */
export function registerOAuthMetadataRoutes(app: Express): void {
  // RFC 9728 — OAuth Protected Resource Metadata.
  app.get("/.well-known/oauth-protected-resource", (req: Request, res: Response) => {
    const entra = loadEntraSettings();
    if (!entra.isConfigured) {
      res.status(503).json({
        error:
          "OAuth metadata not configured. AUTH_CLIENT_ID and AUTH_TENANT_ID environment variables are required.",
      });
      return;
    }

    // Point to our own server as the authorization server metadata host.
    const baseUrl = `${req.protocol}://${req.get("host")}`;

    res.json({
      resource: entra.applicationIdUri,
      authorization_servers: [baseUrl],
      scopes_supported: [entra.requiredScope],
      bearer_methods_supported: ["header"],
    });
  });

  // RFC 8414 — OAuth Authorization Server Metadata.
  app.get("/.well-known/oauth-authorization-server", (_req: Request, res: Response) => {
    const entra = loadEntraSettings();
    if (!entra.isConfigured) {
      res.status(503).json({
        error:
          "OAuth metadata not configured. AUTH_CLIENT_ID and AUTH_TENANT_ID environment variables are required.",
      });
      return;
    }

    res.json({
      issuer: entra.issuer,
      authorization_endpoint: entra.authorizationEndpoint,
      token_endpoint: entra.tokenEndpoint,
      jwks_uri: entra.jwksUri,
      scopes_supported: [
        "openid",
        "profile",
        "email",
        "offline_access",
        entra.delegatedScopeUri,
      ],
      response_types_supported: ["code"],
      grant_types_supported: ["authorization_code", "client_credentials"],
      token_endpoint_auth_methods_supported: ["client_secret_post", "client_secret_basic"],
      code_challenge_methods_supported: ["S256"],
    });
  });
}
