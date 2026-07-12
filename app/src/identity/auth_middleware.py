"""Identity context — FastAPI authentication middleware helpers."""

from __future__ import annotations

import json
import logging
import sys

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from ..shared.server_info import ALLOW_ANONYMOUS_MCP
from .access_token import AccessToken
from .caller_identity import resolve_caller_identity
from .entra_token_validator import TokenValidationError, validate_entra_access_token

logger = logging.getLogger("lgup_mcp.auth")


def _ensure_auth_logger_handler() -> None:
    # Uvicorn config may not route non-uvicorn loggers to console in some
    # runtime configurations. Add a fallback stream handler so [AUTH] logs are
    # always emitted to container stdout/stderr.
    if logger.handlers:
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


_ensure_auth_logger_handler()

_PROTECTED_EXACT_PATHS = {"/drm/decrypt", "/upload"}
_PROTECTED_PREFIX_PATHS = ("/onedrive",)
_PUBLIC_PREFIXES = (
    "/health",
    "/.well-known/",
    "/auth-ui",
    "/drm-ui",
    "/vendor/",
)


def _claims_snapshot_from_authorization(authorization: str | None) -> dict:
    token = AccessToken.from_authorization_header(authorization)
    claims = token.claims if token and isinstance(token.claims, dict) else {}
    return {
        "name": claims.get("name"),
        "unique_name": claims.get("unique_name"),
        "appid": claims.get("appid"),
        "oid": claims.get("oid"),
        "tid": claims.get("tid"),
        "aud": claims.get("aud"),
        "iss": claims.get("iss"),
        "scp": claims.get("scp"),
        "roles": claims.get("roles"),
    }


def _request_context(request: Request) -> dict:
    return {"method": request.method, "path": request.url.path}


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
    requires_auth = _requires_authentication(request)
    required_scopes = _required_scopes_for(request) if requires_auth else []
    logger.info(
        "[AUTH] Request classification: %s",
        json.dumps(
            {
                **_request_context(request),
                "requiresAuthentication": requires_auth,
                "requiredScopes": required_scopes,
            },
            ensure_ascii=False,
        ),
    )
    if not requires_auth:
        return None

    try:
        claims = validate_entra_access_token(
            request.headers.get("authorization"),
            required_scopes=required_scopes,
        )
    except TokenValidationError as error:
        logger.warning(
            "[AUTH] Authentication failed: %s",
            json.dumps(
                {
                    **_request_context(request),
                    "statusCode": error.status_code,
                    "message": error.message,
                    "wwwAuthenticate": error.www_authenticate,
                    "requiredScopes": required_scopes,
                    "tokenClaims": _claims_snapshot_from_authorization(
                        request.headers.get("authorization")
                    ),
                },
                ensure_ascii=False,
            ),
        )
        return _failure_response(request.url.path, error)

    identity = resolve_caller_identity(request.headers)
    identity["name"] = claims.get("name") or identity.get("name")
    identity["unique_name"] = claims.get("unique_name") or identity.get("unique_name")
    identity["appid"] = claims.get("appid") or identity.get("appid")
    if identity.get("scopes") is None:
        identity["scopes"] = claims.get("scp") or claims.get("roles")

    request.state.token_claims = claims
    request.state.caller_identity = identity
    logger.info(
        "[AUTH] Authentication succeeded: %s",
        json.dumps(
            {
                **_request_context(request),
                "requiredScopes": required_scopes,
                "identity": {
                    "name": identity.get("name"),
                    "unique_name": identity.get("unique_name"),
                    "appid": identity.get("appid"),
                    "objectId": identity.get("objectId"),
                    "tenantId": identity.get("tenantId"),
                    "scopes": identity.get("scopes"),
                },
            },
            ensure_ascii=False,
        ),
    )
    return None
