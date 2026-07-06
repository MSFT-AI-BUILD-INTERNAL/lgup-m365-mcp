import type { DrmCredentials } from "./DrmCredentials.js";
import { signDrmRequest } from "./DrmSignature.js";

/**
 * DRM decryption context — Anti-Corruption Layer over the external DRM/MIP
 * decrypt API. It signs the request, forwards the encrypted document, and
 * translates the foreign HTTP response into a domain `DecryptionOutcome` so no
 * other context is coupled to the external service's transport details.
 */
export interface EncryptedDocument {
  readonly buffer: Buffer;
  readonly originalname: string;
  readonly mimetype: string;
}

export type DecryptionOutcome =
  | { readonly ok: true; readonly contentType: string; readonly disposition: string | null; readonly body: Buffer }
  | { readonly ok: false; readonly status: number; readonly body: string };

export async function decryptDocument(
  credentials: DrmCredentials,
  document: EncryptedDocument
): Promise<DecryptionOutcome> {
  const signature = signDrmRequest(credentials);

  const form = new FormData();
  const blob = new Blob([new Uint8Array(document.buffer)], {
    type: document.mimetype || "application/octet-stream",
  });
  form.append("file", blob, document.originalname);

  const upstream = await fetch(credentials.decryptEndpoint, {
    method: "POST",
    headers: {
      "x-client-id": credentials.clientId,
      "x-key-id": credentials.keyId,
      "x-timestamp": signature.timestamp,
      "x-user-email": credentials.email,
      "x-user-loginId": credentials.loginId,
      Authorization: signature.authorizationHeader,
    },
    body: form,
  });

  const contentType = upstream.headers.get("content-type") ?? "application/octet-stream";
  const disposition = upstream.headers.get("content-disposition");

  if (!upstream.ok) {
    return { ok: false, status: upstream.status, body: await upstream.text() };
  }

  const arrayBuffer = await upstream.arrayBuffer();
  return { ok: true, contentType, disposition, body: Buffer.from(arrayBuffer) };
}
