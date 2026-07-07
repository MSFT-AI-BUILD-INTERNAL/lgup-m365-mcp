"""Identity context — ``AccessToken`` Value Object.

Wraps a bearer token and exposes domain behaviour (claim inspection, scope
checks). Decoding reads claims for display/authorisation decisions only; the
cryptographic signature/audience/issuer are validated upstream (APIM / Entra
JWKS). Defined entirely by its raw value, so it is a Value Object.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class AccessToken:
    raw: str
    claims: dict | None

    @classmethod
    def from_authorization_header(cls, header: str | None) -> "AccessToken | None":
        """Build an AccessToken from an HTTP ``Authorization`` header value.

        Returns None when no ``Bearer <token>`` is present.
        """
        if not isinstance(header, str) or not header.lower().startswith("bearer "):
            return None
        raw = header[7:].strip()
        return cls(raw=raw, claims=cls._decode_claims(raw))

    def has_scope(self, scope: str) -> bool:
        """Whether the token carries the given delegated scope (``scp``) or app
        role (``roles``). When claims cannot be decoded, the check defers to
        upstream validation (APIM) and does not block.
        """
        if self.claims is None:
            return True
        scp = self.claims.get("scp")
        scopes = scp.split(" ") if isinstance(scp, str) else []
        roles = self.claims.get("roles")
        roles = roles if isinstance(roles, list) else []
        return scope in [*scopes, *roles]

    @staticmethod
    def _decode_claims(token: str) -> dict | None:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        try:
            padded = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = base64.urlsafe_b64decode(padded).decode("utf-8")
            return json.loads(payload)
        except (ValueError, binascii.Error, json.JSONDecodeError):
            return None
