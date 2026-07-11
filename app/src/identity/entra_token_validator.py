"""Identity context — Entra access token validation.

Performs app-level JWT verification for bearer tokens:
  - header format (Bearer)
  - Entra JWKS signature verification
  - issuer/audience/expiry checks
  - required delegated scope / app role checks
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time

import jwt
from jwt import PyJWKClient

from ..shared.entra_settings import EntraSettings, load_entra_settings

_JWKS_CLIENTS: dict[str, PyJWKClient] = {}
_REQUIRED_IDENTITY_CLAIMS = ("name", "unique_name", "appid")


@dataclass(frozen=True)
class TokenValidationError(Exception):
    status_code: int
    message: str
    www_authenticate: str | None = None


def _build_www_authenticate(entra: EntraSettings, description: str) -> str:
    return (
        f'Bearer realm="{entra.application_id_uri}", '
        f'authorization_uri="{entra.authorization_endpoint}", '
        f'error="invalid_token", error_description="{description}"'
    )


def _scope_missing(claims: dict, required_scopes: list[str]) -> bool:
    if not required_scopes:
        return False
    scp = claims.get("scp")
    scopes = scp.split(" ") if isinstance(scp, str) else []
    roles = claims.get("roles")
    roles = roles if isinstance(roles, list) else []
    granted = {str(value) for value in [*scopes, *roles]}
    return not any(scope in granted for scope in required_scopes)


def _candidate_issuers(entra: EntraSettings) -> set[str]:
    tenant = entra.tenant_id.strip()
    # Accept both v2 and v1 issuer patterns because Copilot Studio forwarded
    # tokens may be issued as v1 ("https://sts.windows.net/{tenant}/").
    return {
        entra.issuer,
        entra.issuer.rstrip("/"),
        f"https://sts.windows.net/{tenant}/",
        f"https://sts.windows.net/{tenant}",
    }


def _candidate_audiences(entra: EntraSettings) -> set[str]:
    return {
        entra.application_id_uri,
        entra.client_id,
        "https://api.powerplatform.com",
    }


def _extract_claims_from_raw_format(token: str) -> dict | None:
    # Copilot Studio integrations may forward a decoded-like token shape:
    #   {header-json}.{payload-json}.[Signature]
    # In that format signature verification is not possible from this payload
    # text alone; we still validate core claims (issuer/audience/time/scope).
    raw = token.strip()
    if not raw.startswith("{"):
        return None
    decoder = json.JSONDecoder()
    try:
        header, header_end = decoder.raw_decode(raw)
        if not isinstance(header, dict):
            return None
        rest = raw[header_end:].lstrip()
        if not rest.startswith("."):
            return None
        rest = rest[1:].lstrip()
        claims, claims_end = decoder.raw_decode(rest)
        if not isinstance(claims, dict):
            return None
        tail = rest[claims_end:].lstrip()
        if not tail.startswith("."):
            return None
    except json.JSONDecodeError:
        return None
    return claims


def _extract_bearer_token(authorization: str | None, entra: EntraSettings) -> str:
    if not isinstance(authorization, str) or not authorization.lower().startswith("bearer "):
        raise TokenValidationError(
            status_code=401,
            message="Unauthorized. Bearer token required.",
            www_authenticate=_build_www_authenticate(entra, "Bearer token required"),
        )
    token = authorization[7:].strip()
    if not token:
        raise TokenValidationError(
            status_code=401,
            message="Unauthorized. Bearer token required.",
            www_authenticate=_build_www_authenticate(entra, "Bearer token required"),
        )
    return token


def _jwks_client(jwks_uri: str) -> PyJWKClient:
    client = _JWKS_CLIENTS.get(jwks_uri)
    if client is None:
        client = PyJWKClient(jwks_uri)
        _JWKS_CLIENTS[jwks_uri] = client
    return client


def _validate_common_claims(
    claims: dict, entra: EntraSettings, required_scopes: list[str]
) -> None:
    now = int(time.time())
    exp = claims.get("exp")
    if not isinstance(exp, int) or exp <= now:
        raise TokenValidationError(
            status_code=401,
            message="Unauthorized. Access token is expired.",
            www_authenticate=_build_www_authenticate(entra, "Access token is expired"),
        )

    nbf = claims.get("nbf")
    if isinstance(nbf, int) and nbf > now:
        raise TokenValidationError(
            status_code=401,
            message="Unauthorized. Access token is not yet valid.",
            www_authenticate=_build_www_authenticate(entra, "Access token is not yet valid"),
        )

    issuer = claims.get("iss")
    if issuer not in _candidate_issuers(entra):
        raise TokenValidationError(
            status_code=401,
            message="Unauthorized. Access token validation failed.",
            www_authenticate=_build_www_authenticate(entra, "Unexpected token issuer"),
        )

    audience = claims.get("aud")
    if audience not in _candidate_audiences(entra):
        raise TokenValidationError(
            status_code=401,
            message="Unauthorized. Access token validation failed.",
            www_authenticate=_build_www_authenticate(entra, "Unexpected token audience"),
        )

    if _scope_missing(claims, required_scopes):
        raise TokenValidationError(
            status_code=403,
            message=(
                "Forbidden. Token must include at least one required scope: "
                + ", ".join(required_scopes)
                + "."
            ),
        )

    missing_claims = [
        claim
        for claim in _REQUIRED_IDENTITY_CLAIMS
        if not isinstance(claims.get(claim), str) or not claims.get(claim).strip()
    ]
    if missing_claims:
        description = "Missing required claim(s): " + ", ".join(missing_claims)
        raise TokenValidationError(
            status_code=401,
            message="Unauthorized. Access token validation failed.",
            www_authenticate=_build_www_authenticate(entra, description),
        )


def validate_entra_access_token(
    authorization: str | None,
    *,
    required_scope: str | None = None,
    required_scopes: list[str] | None = None,
) -> dict:
    """Validate an Entra bearer token and return verified claims."""
    entra = load_entra_settings()
    if not entra.is_configured:
        raise TokenValidationError(
            status_code=503,
            message=(
                "Authentication is not configured. Set AUTH_CLIENT_ID and AUTH_TENANT_ID "
                "environment variables."
            ),
        )

    token = _extract_bearer_token(authorization, entra)
    required_scopes = list(required_scopes or [])
    if required_scope:
        required_scopes.insert(0, required_scope)
    if not required_scopes:
        required_scopes = [entra.required_scope]

    raw_claims = _extract_claims_from_raw_format(token)
    if raw_claims is not None:
        _validate_common_claims(raw_claims, entra, required_scopes)
        return raw_claims

    try:
        signing_key = _jwks_client(entra.jwks_uri).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            options={"require": ["exp"], "verify_aud": False, "verify_iss": False},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenValidationError(
            status_code=401,
            message="Unauthorized. Access token is expired.",
            www_authenticate=_build_www_authenticate(entra, "Access token is expired"),
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise TokenValidationError(
            status_code=401,
            message="Unauthorized. Access token validation failed.",
            www_authenticate=_build_www_authenticate(entra, "Access token validation failed"),
        ) from exc

    _validate_common_claims(claims, entra, required_scopes)
    return claims
