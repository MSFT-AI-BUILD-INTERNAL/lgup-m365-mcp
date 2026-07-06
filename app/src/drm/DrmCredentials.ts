/**
 * DRM decryption context — `DrmCredentials` Value Object.
 *
 * Loads the DRM/MIP client credentials and target host from the environment so
 * secrets never live in code and are never exposed to the browser. Defined
 * entirely by its attributes, so it is a Value Object.
 */
export interface DrmCredentials {
  readonly host: string;
  readonly clientId: string;
  readonly keyId: string;
  readonly secretKey: string;
  readonly email: string;
  readonly loginId: string;
  /** Fully-qualified decrypt endpoint on the DRM host. */
  readonly decryptEndpoint: string;
  /** True once every credential required to call the DRM API is present. */
  readonly isConfigured: boolean;
}

export function loadDrmCredentials(): DrmCredentials {
  const host = process.env.DRM_HOST ?? "seulgiapi.lguplus.co.kr";
  const clientId = process.env.DRM_CLIENT_ID ?? "";
  const keyId = process.env.DRM_KEY_ID ?? "";
  const secretKey = process.env.DRM_SECRET_KEY ?? "";
  const email = process.env.DRM_USER_EMAIL ?? "";
  const loginId = process.env.DRM_USER_LOGINID ?? "";

  return {
    host,
    clientId,
    keyId,
    secretKey,
    email,
    loginId,
    decryptEndpoint: `https://${host}/v1/mip/decrypt`,
    isConfigured: Boolean(clientId && keyId && secretKey && email && loginId),
  };
}
