"""Composition root.

Wires the bounded contexts together behind a single ASGI app.

Production API/MCP surface (always served):
  - drm    : DRM/MIP decrypt proxy (POST /drm/decrypt)
  - oauth  : OAuth discovery metadata (/.well-known/*)
  - mcp    : Streamable HTTP MCP endpoint (/mcp)
  - health : liveness/readiness probe (/health)

Dev/test-only frontend (served only when ENABLE_TEST_UI is set):
  - test_ui : browser test pages (/auth-ui, /drm-ui, /vendor, /auth-ui/config)

The test frontend exists purely to exercise the API/MCP from a browser. Real
clients call /drm/decrypt and /mcp directly, so the UI stays disabled in
production.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .drm.routes import router as drm_router
from .identity.auth_middleware import authenticate_request
from .identity.caller_identity import resolve_caller_identity
from .mcp_server.server import build_mcp
from .oauth.metadata_routes import router as oauth_router
from .shared.server_info import (
    ENABLE_TEST_UI,
    PORT,
    SERVER_NAME,
    SERVER_VERSION,
)
from .storage.routes import router as upload_router

logger = logging.getLogger("lgup_mcp")

_mcp = build_mcp()
_mcp_app = _mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Run the MCP session manager for the mounted Streamable HTTP app.
    async with _mcp.session_manager.run():
        yield


app = FastAPI(title=SERVER_NAME, version=SERVER_VERSION, lifespan=lifespan)


@app.middleware("http")
async def enforce_mcp_scope(request: Request, call_next):
    failure = authenticate_request(request)
    if failure is not None:
        return failure

    if request.url.path == "/mcp" and request.method == "POST":
        user = getattr(request.state, "caller_identity", None) or resolve_caller_identity(
            request.headers
        )
        logger.info(
            "[MCP] Incoming request from: %s",
            json.dumps(
                {
                    "name": user.get("name"),
                    "unique_name": user.get("unique_name"),
                    "appid": user.get("appid"),
                    "displayName": user["displayName"],
                    "userPrincipalName": user["userPrincipalName"],
                    "objectId": user["objectId"],
                    "tenantId": user["tenantId"],
                    "scopes": user["scopes"],
                    "authenticated": user["authenticated"],
                },
                ensure_ascii=False,
            ),
        )
    return await call_next(request)


app.include_router(drm_router)
app.include_router(upload_router)
app.include_router(oauth_router)

# The browser test frontend is dev/test-only and mounted only when explicitly
# enabled, keeping it cleanly separated from the production API/MCP surface.
if ENABLE_TEST_UI:
    from .test_ui.ui_routes import router as test_ui_router

    app.include_router(test_ui_router)
    logger.warning(
        "Test UI ENABLED (/auth-ui, /drm-ui, /vendor, /auth-ui/config). "
        "This is for testing only \u2014 do not enable in production."
    )
else:
    logger.info(
        "Test UI disabled (production mode). Set ENABLE_TEST_UI=1 to serve the "
        "browser test pages."
    )


@app.get("/health")
async def health():
    # Liveness/readiness probe endpoint for Azure Container Apps.
    return JSONResponse(
        {"status": "ok", "server": SERVER_NAME, "version": SERVER_VERSION}
    )


# Mount the MCP Streamable HTTP app last so the explicit routes above take
# precedence; it serves the /mcp endpoint.
app.mount("/", _mcp_app)


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
