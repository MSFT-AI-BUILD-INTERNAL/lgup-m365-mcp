"""Tests for the MCP tools (decrypt / HWP preprocess) exposed on /mcp.

These verify the tools registered by ``build_mcp`` work end-to-end: the DRM API
is mocked with ``httpx.MockTransport`` and HWP/HWPX preprocessing uses the real
stdlib path against the committed fixture. Clients reach these via POST /mcp
(already Entra-protected by APIM validate-jwt), so no new APIM route is needed.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx

from src.mcp_server.server import build_mcp

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _install_mock_transport(monkeypatch, handler) -> None:
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real_client(transport=transport)
    )


def _call(mcp, name: str, args: dict) -> dict:
    """Invoke an MCP tool and return the parsed JSON payload it produced."""

    async def _run():
        return await mcp.call_tool(name, args)

    result = asyncio.run(_run())
    content = result[0] if isinstance(result, tuple) else result
    text = content[0].text
    return json.loads(text)


def test_preprocess_hwp_tool_real_fixture():
    mcp = build_mcp()
    raw = (FIXTURES / "sample_bid_plan_3pages.hwpx").read_bytes()
    b64 = base64.b64encode(raw).decode()

    data = _call(mcp, "preprocess_hwp", {"file_base64": b64, "filename": "sample.hwpx"})

    assert data["status"] == "success"
    assert data["format"] == "hwpx"
    assert data["char_count"] > 0
    assert "발주계획" in data["markdown"]


def test_preprocess_hwp_tool_rejects_bad_base64():
    mcp = build_mcp()
    data = _call(
        mcp, "preprocess_hwp", {"file_base64": "!!!not-base64!!!", "filename": "x.hwpx"}
    )
    assert data["status"] == "error"


def test_drm_decrypt_tool_success(drm_env, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"PLAINTEXT-OK", headers={"content-type": "application/pdf"}
        )

    _install_mock_transport(monkeypatch, handler)

    mcp = build_mcp()
    b64 = base64.b64encode(b"ENCRYPTED").decode()
    data = _call(mcp, "drm_decrypt", {"file_base64": b64, "filename": "s.hwp"})

    assert data["status"] == "success"
    assert base64.b64decode(data["content_base64"]) == b"PLAINTEXT-OK"
    assert data["content_type"] == "application/pdf"


def test_drm_decrypt_tool_not_configured(monkeypatch):
    for key in (
        "DRM_CLIENT_ID",
        "DRM_KEY_ID",
        "DRM_SECRET_KEY",
        "DRM_USER_EMAIL",
        "DRM_USER_LOGINID",
    ):
        monkeypatch.delenv(key, raising=False)

    mcp = build_mcp()
    b64 = base64.b64encode(b"ENCRYPTED").decode()
    data = _call(mcp, "drm_decrypt", {"file_base64": b64, "filename": "s.hwp"})
    assert data["status"] == "error"


def test_decrypt_and_preprocess_tool(drm_env, monkeypatch):
    # DRM "decrypts" to the real HWPX fixture bytes, which then get preprocessed.
    fixture_bytes = (FIXTURES / "sample_bid_plan_3pages.hwpx").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=fixture_bytes, headers={"content-type": "application/octet-stream"}
        )

    _install_mock_transport(monkeypatch, handler)

    mcp = build_mcp()
    b64 = base64.b64encode(b"ENCRYPTED-HWPX").decode()
    data = _call(
        mcp, "decrypt_and_preprocess", {"file_base64": b64, "filename": "doc.hwpx"}
    )

    assert data["status"] == "success"
    assert data["format"] == "hwpx"
    assert "발주계획" in data["markdown"]
