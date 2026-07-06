/**
 * Entra ID (Azure AD) settings expressed in the ubiquitous language of the
 * authentication domain. This is a Value Object derived from environment
 * configuration; it centralises every Entra-specific URL and identifier so no
 * other context has to hand-build them.
 */

/** The delegated permission this API requires callers to hold. */
export const REQUIRED_SCOPE = "access_as_user";

export interface EntraSettings {
  readonly tenantId: string;
  readonly clientId: string;
  readonly requiredScope: string;
  /** True once both tenant and client identifiers are present. */
  readonly isConfigured: boolean;
  /** Application ID URI that identifies this API as a resource: `api://<clientId>`. */
  readonly applicationIdUri: string;
  /** Fully-qualified delegated scope: `api://<clientId>/<scope>`. */
  readonly delegatedScopeUri: string;
  readonly authority: string;
  readonly issuer: string;
  readonly authorizationEndpoint: string;
  readonly tokenEndpoint: string;
  readonly jwksUri: string;
}

/** Load the current Entra settings from the environment. */
export function loadEntraSettings(): EntraSettings {
  const tenantId = process.env.AUTH_TENANT_ID ?? "";
  const clientId = process.env.AUTH_CLIENT_ID ?? "";
  const authority = `https://login.microsoftonline.com/${tenantId}`;

  return {
    tenantId,
    clientId,
    requiredScope: REQUIRED_SCOPE,
    isConfigured: Boolean(tenantId && clientId),
    applicationIdUri: `api://${clientId}`,
    delegatedScopeUri: `api://${clientId}/${REQUIRED_SCOPE}`,
    authority,
    issuer: `${authority}/v2.0`,
    authorizationEndpoint: `${authority}/oauth2/v2.0/authorize`,
    tokenEndpoint: `${authority}/oauth2/v2.0/token`,
    jwksUri: `${authority}/discovery/v2.0/keys`,
  };
}
