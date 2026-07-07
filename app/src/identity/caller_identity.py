"""Identity context — ``CallerIdentity`` and its resolver.

The resolver is an Anti-Corruption Layer: it translates the two foreign
authentication mechanisms that can front this server into a single domain
identity, so the rest of the code never touches raw Easy Auth headers or JWTs.

 1. Azure Container Apps "Easy Auth" injected headers (x-ms-client-principal*).
 2. A forwarded Entra ID bearer token in the Authorization header.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Mapping

from .access_token import AccessToken


def resolve_caller_identity(headers: Mapping[str, str]) -> dict[str, Any]:
    def header(name: str) -> str | None:
        value = headers.get(name)
        return value if isinstance(value, str) else None

    # 1) Easy Auth simple headers.
    principal_name = header("x-ms-client-principal-name")
    principal_id = header("x-ms-client-principal-id")
    principal_idp = header("x-ms-client-principal-idp")

    # 1b) Easy Auth full base64-encoded principal (claims array).
    easy_auth_claims: dict | None = None
    encoded_principal = header("x-ms-client-principal")
    if encoded_principal:
        try:
            easy_auth_claims = json.loads(
                base64.b64decode(encoded_principal).decode("utf-8")
            )
        except (ValueError, json.JSONDecodeError):
            easy_auth_claims = None

    # 2) Bearer token claims.
    token = AccessToken.from_authorization_header(header("authorization"))
    claims: dict = token.claims if token and token.claims else {}

    display_name = (
        principal_name
        or claims.get("name")
        or claims.get("preferred_username")
        or claims.get("upn")
    )
    user_id = principal_id or claims.get("oid") or claims.get("sub")

    authenticated = bool(display_name or user_id or easy_auth_claims)

    return {
        "authenticated": authenticated,
        "displayName": display_name or None,
        "userPrincipalName": (
            claims.get("preferred_username") or claims.get("upn") or principal_name
        ),
        "email": claims.get("email") or None,
        "objectId": user_id or None,
        "tenantId": claims.get("tid") or None,
        "identityProvider": principal_idp,
        "scopes": claims.get("scp") or claims.get("roles") or None,
    }
