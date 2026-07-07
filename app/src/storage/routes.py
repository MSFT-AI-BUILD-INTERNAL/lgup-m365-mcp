"""Storage context — file upload HTTP endpoint.

Accepts a file upload, persists it to Azure Blob Storage, then forwards it to
the DRM decrypt API. Returns both the blob metadata and the decrypted content
(or an error from the DRM service).

Flow:
  Client ──► POST /upload ──► Blob Storage (persist original)
                           ──► DRM /v1/mip/decrypt (decrypt)
                           ◄── { blob metadata + decryption result }
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from ..drm.credentials import load_drm_credentials
from ..drm.decryption_client import EncryptedDocument, decrypt_document
from ..identity.scope_guard import scope_failure_response
from .blob_client import BlobUploadResult, upload_blob
from .settings import load_storage_settings

logger = logging.getLogger("lgup_mcp.storage")

router = APIRouter()


def _blob_with_drm_response(
    blob_result: BlobUploadResult,
    drm_info: dict[str, Any],
    *,
    status_code: int = 200,
) -> JSONResponse:
    """Build a JSON response containing blob metadata and DRM status."""
    return JSONResponse(
        status_code=status_code,
        content={"blob": blob_result.to_dict(), "drm": drm_info},
    )


@router.post("/upload")
async def upload_file(request: Request, file: UploadFile | None = File(default=None)):
    """Upload a file to Blob Storage and forward it to the DRM decrypt API."""
    failure = scope_failure_response(request.headers.get("authorization"))
    if failure is not None:
        return failure

    if file is None:
        return JSONResponse(
            status_code=400, content={"error": "No file uploaded. Attach a 'file' field."}
        )

    file_bytes = await file.read()
    filename = file.filename or "upload.bin"
    content_type = file.content_type or "application/octet-stream"

    # --- 1. Upload to Blob Storage ---
    storage_settings = load_storage_settings()
    if not storage_settings.is_configured:
        return JSONResponse(
            status_code=503,
            content={
                "error": (
                    "Blob Storage is not configured. Set AZURE_STORAGE_ACCOUNT_URL "
                    "or AZURE_STORAGE_CONNECTION_STRING environment variable."
                )
            },
        )

    try:
        blob_result = await upload_blob(storage_settings, file_bytes, filename, content_type)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Blob upload failed")
        return JSONResponse(
            status_code=502,
            content={"error": "Failed to upload file to Blob Storage.", "detail": str(exc)},
        )

    logger.info(
        "[Upload] Stored blob: %s (%d bytes)", blob_result.blob_name, blob_result.size
    )

    # --- 2. Forward to DRM decrypt ---
    drm_credentials = load_drm_credentials()
    if not drm_credentials.is_configured:
        return _blob_with_drm_response(
            blob_result,
            {"status": "skipped", "reason": "DRM proxy is not configured."},
        )

    document = EncryptedDocument(
        buffer=file_bytes, filename=filename, content_type=content_type
    )

    try:
        outcome = await decrypt_document(drm_credentials, document)
    except Exception as exc:  # noqa: BLE001
        logger.exception("DRM decrypt proxy error during upload flow")
        return _blob_with_drm_response(
            blob_result, {"status": "error", "detail": str(exc)}, status_code=502
        )

    if not outcome.ok:
        return _blob_with_drm_response(
            blob_result,
            {
                "status": "failed",
                "upstream_status": outcome.status,
                "body": outcome.body,
            },
        )

    # DRM succeeded — return decrypted content with blob info in headers.
    disposition = outcome.disposition or f'attachment; filename="decrypted-{filename}"'
    return Response(
        content=outcome.body,
        media_type=outcome.content_type,
        headers={
            "Content-Disposition": disposition,
            "X-Blob-Name": blob_result.blob_name,
            "X-Blob-Url": blob_result.url,
        },
    )
