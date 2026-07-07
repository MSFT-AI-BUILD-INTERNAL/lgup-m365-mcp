"""DRM decryption context — ``DrmSignature`` Value Object.

Encapsulates the SEULGI-HMAC-SHA256-V1 request signing scheme: an HMAC over
``host;clientId;keyId;timestamp;email;loginId`` keyed by the secret key. The
signature is a Value Object defined by its timestamp and authorization header.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass

from .credentials import DrmCredentials


@dataclass(frozen=True)
class DrmSignature:
    timestamp: str
    authorization_header: str


def sign_drm_request(
    credentials: DrmCredentials, timestamp: str | None = None
) -> DrmSignature:
    timestamp = timestamp or str(int(time.time()))
    signing_string = ";".join(
        [
            credentials.host,
            credentials.client_id,
            credentials.key_id,
            timestamp,
            credentials.email,
            credentials.login_id,
        ]
    )
    digest = hmac.new(
        credentials.secret_key.encode("utf-8"),
        signing_string.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature = base64.b64encode(digest).decode("ascii")
    authorization_header = (
        "SEULGI-HMAC-SHA256-V1 "
        "SigHeaders=host;x-client-id;x-key-id;x-timestamp,x-user-email,"
        f"Signature={signature}"
    )
    return DrmSignature(timestamp=timestamp, authorization_header=authorization_header)
