"""OAuth discovery context — advertises this server's auth requirements and the
backing Entra ID endpoints so OAuth-aware MCP clients can auto-discover them.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..shared.entra_settings import load_entra_settings

router = APIRouter()

_NOT_CONFIGURED = {
    "error": (
        "OAuth metadata not configured. AUTH_CLIENT_ID and AUTH_TENANT_ID "
        "environment variables are required."
    )
}


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(request: Request):
    """RFC 9728 — OAuth Protected Resource Metadata."""
    entra = load_entra_settings()
    if not entra.is_configured:
        return JSONResponse(status_code=503, content=_NOT_CONFIGURED)

    base_url = f"{request.url.scheme}://{request.headers.get('host', '')}"
    return {
        "resource": entra.application_id_uri,
        "authorization_servers": [base_url],
        "scopes_supported": [entra.required_scope],
        "bearer_methods_supported": ["header"],
    }


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata():
    """RFC 8414 — OAuth Authorization Server Metadata."""
    entra = load_entra_settings()
    if not entra.is_configured:
        return JSONResponse(status_code=503, content=_NOT_CONFIGURED)

    return {
        "issuer": entra.issuer,
        "authorization_endpoint": entra.authorization_endpoint,
        "token_endpoint": entra.token_endpoint,
        "jwks_uri": entra.jwks_uri,
        "scopes_supported": [
            "openid",
            "profile",
            "email",
            "offline_access",
            entra.delegated_scope_uri,
        ],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "client_credentials"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_post",
            "client_secret_basic",
        ],
        "code_challenge_methods_supported": ["S256"],
    }
