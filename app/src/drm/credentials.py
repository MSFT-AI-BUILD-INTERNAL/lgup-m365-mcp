"""DRM decryption context — ``DrmCredentials`` Value Object.

Loads the DRM/MIP client credentials and target host from the environment so
secrets never live in code and are never exposed to the browser. Defined
entirely by its attributes, so it is a Value Object.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DrmCredentials:
    host: str
    client_id: str
    key_id: str
    secret_key: str
    email: str
    login_id: str

    @property
    def decrypt_endpoint(self) -> str:
        """Fully-qualified decrypt endpoint on the DRM host."""
        return f"https://{self.host}/v1/mip/decrypt"

    @property
    def is_configured(self) -> bool:
        """True once every credential required to call the DRM API is present."""
        return all(
            [self.client_id, self.key_id, self.secret_key, self.email, self.login_id]
        )


def load_drm_credentials() -> DrmCredentials:
    return DrmCredentials(
        host=os.environ.get("DRM_HOST", "seulgiapi.lguplus.co.kr"),
        client_id=os.environ.get("DRM_CLIENT_ID", ""),
        key_id=os.environ.get("DRM_KEY_ID", ""),
        secret_key=os.environ.get("DRM_SECRET_KEY", ""),
        email=os.environ.get("DRM_USER_EMAIL", ""),
        login_id=os.environ.get("DRM_USER_LOGINID", ""),
    )
