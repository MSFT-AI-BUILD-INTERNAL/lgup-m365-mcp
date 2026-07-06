import type { Request, Response } from "express";
import { AccessToken } from "./AccessToken.js";
import { loadEntraSettings } from "../shared/entraSettings.js";

/**
 * Identity context — access-control policy.
 *
 * Validates that the incoming request carries a token with the required scope.
 * APIM performs primary JWT signature/audience/issuer validation; this is a
 * defence-in-depth check ensuring the correct delegated permission is present.
 *
 * Returns true when the request may proceed; otherwise writes the appropriate
 * 401/403 JSON-RPC error and returns false.
 */
export function requireScope(req: Request, res: Response): boolean {
  const entra = loadEntraSettings();
  const token = AccessToken.fromAuthorizationHeader(req.headers["authorization"]);

  if (!token) {
    res.setHeader(
      "WWW-Authenticate",
      `Bearer realm="${entra.applicationIdUri}", authorization_uri="${entra.authorizationEndpoint}"`
    );
    res.status(401).json({
      jsonrpc: "2.0",
      error: { code: -32000, message: "Unauthorized. Bearer token required." },
      id: null,
    });
    return false;
  }

  if (!token.hasScope(entra.requiredScope)) {
    res.status(403).json({
      jsonrpc: "2.0",
      error: {
        code: -32000,
        message: `Forbidden. Token must include the '${entra.requiredScope}' scope.`,
      },
      id: null,
    });
    return false;
  }

  return true;
}
