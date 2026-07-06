"""Presentation layer — browser-facing test UIs.

Serves the Entra login + MCP API test page, the login-gated DRM decrypt page, a
small config endpoint, and the MSAL browser bundle (locally, to avoid an
external CDN dependency).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from ..shared.entra_settings import load_entra_settings
from ..shared.server_info import MSAL_BROWSER_PATH

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_AUTH_TEMPLATE = (_TEMPLATES_DIR / "auth_test_ui.html").read_text(encoding="utf-8")
_DRM_TEMPLATE = (_TEMPLATES_DIR / "drm_test_ui.html").read_text(encoding="utf-8")


def _render(template: str, tenant_id: str, client_id: str, scope: str) -> str:
    return (
        template.replace("{{TENANT_ID}}", tenant_id)
        .replace("{{CLIENT_ID}}", client_id)
        .replace("{{SCOPE}}", scope)
    )


@router.get("/vendor/msal-browser.min.js")
async def msal_browser_bundle():
    # Serve the MSAL browser library locally so the login UIs work without an external CDN.
    return FileResponse(MSAL_BROWSER_PATH, media_type="application/javascript")


@router.get("/auth-ui/config")
async def auth_ui_config():
    entra = load_entra_settings()
    return {
        "tenantId": entra.tenant_id,
        "clientId": entra.client_id,
        "scope": entra.delegated_scope_uri if entra.client_id else "",
    }


@router.get("/auth-ui", response_class=HTMLResponse)
async def auth_ui():
    entra = load_entra_settings()
    if not entra.is_configured:
        return PlainTextResponse(
            status_code=503,
            content="AUTH_CLIENT_ID / AUTH_TENANT_ID environment variables are required for Entra ID test UI.",
        )
    return HTMLResponse(
        _render(_AUTH_TEMPLATE, entra.tenant_id, entra.client_id, entra.delegated_scope_uri)
    )


@router.get("/drm-ui", response_class=HTMLResponse)
async def drm_ui():
    entra = load_entra_settings()
    if not entra.is_configured:
        return PlainTextResponse(
            status_code=503,
            content="AUTH_CLIENT_ID / AUTH_TENANT_ID environment variables are required for the DRM test UI.",
        )
    return HTMLResponse(
        _render(_DRM_TEMPLATE, entra.tenant_id, entra.client_id, entra.delegated_scope_uri)
    )
