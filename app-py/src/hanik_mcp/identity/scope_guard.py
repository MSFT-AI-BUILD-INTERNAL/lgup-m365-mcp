"""Identity context — access-control policy.

Validates that a request carries a token with the required scope. APIM performs
primary JWT signature/audience/issuer validation; this is a defence-in-depth
check ensuring the correct delegated permission is present.

Returns a Starlette ``Response`` describing the 401/403 failure, or ``None`` when
the request may proceed.
"""

from __future__ import annotations

from starlette.responses import JSONResponse, Response

from .access_token import AccessToken
from ..shared.entra_settings import load_entra_settings


def scope_failure_response(authorization: str | None) -> Response | None:
    entra = load_entra_settings()
    token = AccessToken.from_authorization_header(authorization)

    if token is None:
        return JSONResponse(
            status_code=401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer realm="{entra.application_id_uri}", '
                    f'authorization_uri="{entra.authorization_endpoint}"'
                )
            },
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": "Unauthorized. Bearer token required."},
                "id": None,
            },
        )

    if not token.has_scope(entra.required_scope):
        return JSONResponse(
            status_code=403,
            content={
                "jsonrpc": "2.0",
                "error": {
                    "code": -32000,
                    "message": f"Forbidden. Token must include the '{entra.required_scope}' scope.",
                },
                "id": None,
            },
        )

    return None
