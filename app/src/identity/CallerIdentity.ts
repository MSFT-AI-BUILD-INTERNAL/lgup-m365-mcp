import type { Request } from "express";
import { AccessToken } from "./AccessToken.js";

/**
 * Identity context — `CallerIdentity` Value Object and its resolver.
 *
 * The resolver is an Anti-Corruption Layer: it translates the two foreign
 * authentication mechanisms that can front this server into a single domain
 * identity, so the rest of the code never touches raw Easy Auth headers or JWTs.
 *  1. Azure Container Apps "Easy Auth" injected headers (x-ms-client-principal*).
 *  2. A forwarded Entra ID bearer token in the Authorization header.
 */
export interface CallerIdentity {
  authenticated: boolean;
  displayName: string | null;
  userPrincipalName: string | null;
  email: string | null;
  objectId: string | null;
  tenantId: string | null;
  identityProvider: string | null;
  scopes: string | string[] | null;
}

export function resolveCallerIdentity(req: Request): CallerIdentity {
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
  const token = AccessToken.fromAuthorizationHeader(headers["authorization"]);
  const claims = token?.claims ?? {};

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
