"""Entra ID (Azure AD) settings expressed in the ubiquitous language of the
authentication domain.

This is a Value Object derived from environment configuration; it centralises
every Entra-specific URL and identifier so no other context has to hand-build
them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# The delegated permission this API requires callers to hold.
REQUIRED_SCOPE = "access_as_user"


@dataclass(frozen=True)
class EntraSettings:
    tenant_id: str
    client_id: str
    required_scope: str = REQUIRED_SCOPE

    @property
    def is_configured(self) -> bool:
        """True once both tenant and client identifiers are present."""
        return bool(self.tenant_id and self.client_id)

    @property
    def application_id_uri(self) -> str:
        """Application ID URI that identifies this API as a resource."""
        return f"api://{self.client_id}"

    @property
    def delegated_scope_uri(self) -> str:
        """Fully-qualified delegated scope: ``api://<clientId>/<scope>``."""
        return f"api://{self.client_id}/{self.required_scope}"

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"

    @property
    def issuer(self) -> str:
        return f"{self.authority}/v2.0"

    @property
    def authorization_endpoint(self) -> str:
        return f"{self.authority}/oauth2/v2.0/authorize"

    @property
    def token_endpoint(self) -> str:
        return f"{self.authority}/oauth2/v2.0/token"

    @property
    def jwks_uri(self) -> str:
        return f"{self.authority}/discovery/v2.0/keys"


def load_entra_settings() -> EntraSettings:
    """Load the current Entra settings from the environment."""
    return EntraSettings(
        tenant_id=os.environ.get("AUTH_TENANT_ID", ""),
        client_id=os.environ.get("AUTH_CLIENT_ID", ""),
        required_scope=REQUIRED_SCOPE,
    )
