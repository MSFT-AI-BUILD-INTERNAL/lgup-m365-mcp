"""DRM decryption context — Anti-Corruption Layer over the external DRM/MIP
decrypt API.

Signs the request, forwards the encrypted document, and translates the foreign
HTTP response into a domain ``DecryptionOutcome`` so no other context is coupled
to the external service's transport details.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .credentials import DrmCredentials
from .signature import sign_drm_request


@dataclass(frozen=True)
class EncryptedDocument:
    buffer: bytes
    filename: str
    content_type: str


@dataclass(frozen=True)
class DecryptionSuccess:
    ok: bool  # always True
    content_type: str
    disposition: str | None
    body: bytes


@dataclass(frozen=True)
class DecryptionFailure:
    ok: bool  # always False
    status: int
    body: str


DecryptionOutcome = DecryptionSuccess | DecryptionFailure


async def decrypt_document(
    credentials: DrmCredentials, document: EncryptedDocument
) -> DecryptionOutcome:
    signature = sign_drm_request(credentials)

    files = {
        "file": (
            document.filename,
            document.buffer,
            document.content_type or "application/octet-stream",
        )
    }
    headers = {
        "x-client-id": credentials.client_id,
        "x-key-id": credentials.key_id,
        "x-timestamp": signature.timestamp,
        "x-user-email": credentials.email,
        "x-user-loginId": credentials.login_id,
        "Authorization": signature.authorization_header,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        upstream = await client.post(
            credentials.decrypt_endpoint, files=files, headers=headers
        )

    content_type = upstream.headers.get("content-type", "application/octet-stream")
    disposition = upstream.headers.get("content-disposition")

    if upstream.status_code >= 400:
        return DecryptionFailure(ok=False, status=upstream.status_code, body=upstream.text)

    return DecryptionSuccess(
        ok=True, content_type=content_type, disposition=disposition, body=upstream.content
    )
