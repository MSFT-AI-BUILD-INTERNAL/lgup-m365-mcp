import { createHmac } from "node:crypto";
import type { DrmCredentials } from "./DrmCredentials.js";

/**
 * DRM decryption context — `DrmSignature` Value Object.
 *
 * Encapsulates the SEULGI-HMAC-SHA256-V1 request signing scheme: an HMAC over
 * `host;clientId;keyId;timestamp;email;loginId` keyed by the secret key. The
 * signature is a Value Object defined by its timestamp and authorization header.
 */
export interface DrmSignature {
  readonly timestamp: string;
  readonly authorizationHeader: string;
}

export function signDrmRequest(
  credentials: DrmCredentials,
  timestamp: string = Math.floor(Date.now() / 1000).toString()
): DrmSignature {
  const signingString = [
    credentials.host,
    credentials.clientId,
    credentials.keyId,
    timestamp,
    credentials.email,
    credentials.loginId,
  ].join(";");

  const hmac = createHmac("sha256", credentials.secretKey)
    .update(signingString)
    .digest("base64");

  const authorizationHeader = `SEULGI-HMAC-SHA256-V1 SigHeaders=host;x-client-id;x-key-id;x-timestamp,x-user-email,Signature=${hmac}`;

  return { timestamp, authorizationHeader };
}
