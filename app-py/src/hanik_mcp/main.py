"""Composition root.

Wires the bounded contexts together behind a single ASGI app:
  - presentation  : browser test UIs (/auth-ui, /drm-ui, /vendor, /auth-ui/config)
  - drm           : DRM/MIP decrypt proxy (/drm/decrypt)
  - oauth         : OAuth discovery metadata (/.well-known/*)
  - mcp           : Streamable HTTP MCP endpoint (/mcp)
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .drm.routes import router as drm_router
from .identity.caller_identity import resolve_caller_identity
from .identity.scope_guard import scope_failure_response
from .mcp_server.server import build_mcp
from .oauth.metadata_routes import router as oauth_router
from .presentation.ui_routes import router as ui_router
from .shared.server_info import PORT, SERVER_NAME, SERVER_VERSION

logger = logging.getLogger("hanik_mcp")

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
    # Defence-in-depth scope check on the MCP endpoint (APIM validates the JWT).
    if request.url.path == "/mcp" and request.method == "POST":
        failure = scope_failure_response(request.headers.get("authorization"))
        if failure is not None:
            return failure
        user = resolve_caller_identity(request.headers)
        logger.info(
            "[MCP] Incoming request from: %s",
            json.dumps(
                {
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


app.include_router(ui_router)
app.include_router(drm_router)
app.include_router(oauth_router)


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
