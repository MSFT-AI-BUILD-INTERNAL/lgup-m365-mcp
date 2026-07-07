"""DRM decryption context — HTTP endpoint.

Server-side proxy for the DRM/MIP decrypt API. Secrets are read from the
environment (see ``DrmCredentials``) so they are never exposed to the browser;
the HMAC signature is computed server-side and the uploaded file is forwarded to
the DRM API. Requires a valid Entra bearer token with the delegated scope.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from ..identity.scope_guard import scope_failure_response
from .credentials import load_drm_credentials
from .decryption_client import EncryptedDocument, decrypt_document

logger = logging.getLogger("lgup_mcp.drm")

router = APIRouter()


@router.post("/drm/decrypt")
async def drm_decrypt(request: Request, file: UploadFile | None = File(default=None)):
    failure = scope_failure_response(request.headers.get("authorization"))
    if failure is not None:
        return failure

    credentials = load_drm_credentials()
    if not credentials.is_configured:
        return JSONResponse(
            status_code=503,
            content={
                "error": (
                    "DRM proxy is not configured. Set DRM_CLIENT_ID, DRM_KEY_ID, "
                    "DRM_SECRET_KEY, DRM_USER_EMAIL and DRM_USER_LOGINID environment "
                    "variables."
                )
            },
        )

    if file is None:
        return JSONResponse(
            status_code=400, content={"error": "No file uploaded. Attach a 'file' field."}
        )

    document = EncryptedDocument(
        buffer=await file.read(),
        filename=file.filename or "upload.bin",
        content_type=file.content_type or "application/octet-stream",
    )

    try:
        outcome = await decrypt_document(credentials, document)
    except Exception as error:  # noqa: BLE001 - translate any transport failure
        logger.exception("DRM decrypt proxy error")
        return JSONResponse(
            status_code=502,
            content={"error": "Failed to reach the DRM API.", "detail": str(error)},
        )

    if not outcome.ok:
        return JSONResponse(
            status_code=outcome.status,
            content={
                "error": "DRM API returned an error.",
                "status": outcome.status,
                "body": outcome.body,
            },
        )

    disposition = outcome.disposition or f'attachment; filename="decrypted-{document.filename}"'
    return Response(
        content=outcome.body,
        media_type=outcome.content_type,
        headers={"Content-Disposition": disposition},
    )
