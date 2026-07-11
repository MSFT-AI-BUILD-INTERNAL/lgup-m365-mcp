"""Identity context — FastAPI authentication middleware helpers."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from ..shared.server_info import ALLOW_ANONYMOUS_MCP
from .caller_identity import resolve_caller_identity
from .entra_token_validator import TokenValidationError, validate_entra_access_token

_PROTECTED_EXACT_PATHS = {"/drm/decrypt", "/upload"}
_PROTECTED_PREFIX_PATHS = ("/onedrive",)
_PUBLIC_PREFIXES = (
    "/health",
    "/.well-known/",
    "/auth-ui",
    "/drm-ui",
    "/vendor/",
)


def _required_scopes_for(request: Request) -> list[str]:
    if request.url.path == "/mcp" and request.method == "POST":
        # Copilot Studio forwarded tokens typically carry this delegated scope.
        return ["access_as_user", "CopilotStudio.AgentNodes.Invoke"]
    return ["access_as_user"]


def _requires_authentication(request: Request) -> bool:
    path = request.url.path
    if path == "/mcp" and request.method == "POST":
        return not ALLOW_ANONYMOUS_MCP
    if path in _PROTECTED_EXACT_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in _PROTECTED_PREFIX_PATHS):
        return True
    if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
        return False
    return False


def _failure_response(path: str, error: TokenValidationError) -> Response:
    headers = (
        {"WWW-Authenticate": error.www_authenticate}
        if error.www_authenticate is not None
        else None
    )
    if path == "/mcp":
        return JSONResponse(
            status_code=error.status_code,
            headers=headers,
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": error.message},
                "id": None,
            },
        )
    return JSONResponse(status_code=error.status_code, headers=headers, content={"error": error.message})


def authenticate_request(request: Request) -> Response | None:
    """Authenticate protected requests and place verified identity on request state."""
    if not _requires_authentication(request):
        return None

    try:
        claims = validate_entra_access_token(
            request.headers.get("authorization"),
            required_scopes=_required_scopes_for(request),
        )
    except TokenValidationError as error:
        return _failure_response(request.url.path, error)

    identity = resolve_caller_identity(request.headers)
    identity["name"] = claims.get("name") or identity.get("name")
    identity["unique_name"] = claims.get("unique_name") or identity.get("unique_name")
    identity["appid"] = claims.get("appid") or identity.get("appid")
    if identity.get("scopes") is None:
        identity["scopes"] = claims.get("scp") or claims.get("roles")

    request.state.token_claims = claims
    request.state.caller_identity = identity
    return None
