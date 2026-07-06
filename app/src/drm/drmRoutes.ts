import type { Express, Request, Response } from "express";
import multer from "multer";
import { requireScope } from "../identity/scopeGuard.js";
import { loadDrmCredentials } from "./DrmCredentials.js";
import { decryptDocument } from "./DrmDecryptionClient.js";

/**
 * DRM decryption context — HTTP endpoint.
 *
 * Server-side proxy for the DRM/MIP decrypt API. Secrets are read from the
 * environment (see DrmCredentials) so they are never exposed to the browser;
 * the HMAC signature is computed server-side and the uploaded file is forwarded
 * to the DRM API. Requires a valid Entra bearer token with the delegated scope.
 */
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 50 * 1024 * 1024 },
});

export function registerDrmRoutes(app: Express): void {
  app.post("/drm/decrypt", upload.single("file"), async (req: Request, res: Response) => {
    if (!requireScope(req, res)) return;

    const credentials = loadDrmCredentials();
    if (!credentials.isConfigured) {
      res.status(503).json({
        error:
          "DRM proxy is not configured. Set DRM_CLIENT_ID, DRM_KEY_ID, DRM_SECRET_KEY, DRM_USER_EMAIL and DRM_USER_LOGINID environment variables.",
      });
      return;
    }

    const file = (req as Request & {
      file?: { buffer: Buffer; originalname: string; mimetype: string };
    }).file;
    if (!file) {
      res.status(400).json({ error: "No file uploaded. Attach a 'file' field." });
      return;
    }

    try {
      const outcome = await decryptDocument(credentials, file);
      if (!outcome.ok) {
        res.status(outcome.status).json({
          error: "DRM API returned an error.",
          status: outcome.status,
          body: outcome.body,
        });
        return;
      }

      res.status(200);
      res.setHeader("Content-Type", outcome.contentType);
      res.setHeader(
        "Content-Disposition",
        outcome.disposition ?? `attachment; filename="decrypted-${file.originalname}"`
      );
      res.send(outcome.body);
    } catch (error) {
      console.error("DRM decrypt proxy error:", error);
      res.status(502).json({
        error: "Failed to reach the DRM API.",
        detail: error instanceof Error ? error.message : String(error),
      });
    }
  });
}
