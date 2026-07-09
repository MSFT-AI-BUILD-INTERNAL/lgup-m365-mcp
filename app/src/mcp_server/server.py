"""MCP context — server factory.

Builds the MCP server (stateless Streamable HTTP) and registers its tools.
Stateless mode keeps the server simple and horizontally scalable on Azure
Container Apps, mirroring the original TypeScript implementation.

Transport settings:
  - json_response=True: Copilot Studio expects plain JSON responses
    (application/json). SSE streaming causes 406 errors when APIM or
    the client does not forward `Accept: text/event-stream`.
  - DNS rebinding protection is DISABLED because the server runs behind
    Azure APIM / Container Apps ingress which performs Host validation
    at the network edge. The SDK default (localhost-only) rejects
    external callers with HTTP 421.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from ..drm.credentials import load_drm_credentials
from ..drm.decryption_client import (
    DecryptionSuccess,
    EncryptedDocument,
    decrypt_document,
)from mcp.server.transport_security import TransportSecuritySettings

from ..identity.caller_identity import resolve_caller_identity
from ..preprocess.core import blocks_to_markdown
from ..preprocess.service import preprocess_bytes
from ..shared.server_info import SERVER_NAME


def _decode_base64(file_base64: str) -> bytes | None:
    try:
        return base64.b64decode(file_base64, validate=True)
    except Exception:  # noqa: BLE001
        return None


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        SERVER_NAME,
        stateless_http=True,
        # The SDK's DNS-rebinding Host/Origin check targets local browser-facing
        # MCP servers. This server is a hosted API protected by APIM validate-jwt
        # + Container Apps Easy Auth + the scope guard, and sits behind a gateway
        # whose forwarded Host differs from any fixed allow-list, so the check
        # would reject legitimate traffic (421 Misdirected Request). Disable it.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )

    @mcp.tool(
        name="test_lgup",
        title="Test LGUP",
        description="A connectivity test tool that returns a fixed confirmation message.",
    )
    async def test_lgup() -> str:
        return "test lgup mcp ok"

    @mcp.tool(
        name="get_current_user",
        title="Get Current User",
        description=(
            "Returns information about the connected user (Copilot Studio caller) "
            "derived from the forwarded identity headers or bearer token."
        ),
    )
    async def get_current_user() -> str:
        request = mcp.get_context().request_context.request
        headers = request.headers if request is not None else {}
        user = resolve_caller_identity(headers)
        if user["authenticated"]:
            return json.dumps(user, indent=2, ensure_ascii=False)
        return (
            "No user identity was forwarded to the MCP server. The endpoint is "
            "currently unauthenticated, so enable authentication on the Container "
            "App / APIM and configure Copilot Studio to forward the user token to "
            "receive caller details."
        )

    @mcp.tool(
        name="drm_decrypt",
        title="DRM Decrypt",
        description=(
            "Decrypt a DRM/MIP-protected file. Input: 'file_base64' (base64 of the "
            "encrypted bytes) and 'filename'. Returns a JSON string with the "
            "decrypted content as base64 plus metadata. Requires DRM_* env config."
        ),
    )
    async def drm_decrypt(file_base64: str, filename: str = "upload.bin") -> str:
        credentials = load_drm_credentials()
        if not credentials.is_configured:
            return json.dumps(
                {"status": "error", "error": "DRM is not configured (set DRM_* env vars)."},
                ensure_ascii=False,
            )

        raw = _decode_base64(file_base64)
        if raw is None:
            return json.dumps(
                {"status": "error", "error": "file_base64 is not valid base64."},
                ensure_ascii=False,
            )

        document = EncryptedDocument(
            buffer=raw, filename=filename, content_type="application/octet-stream"
        )
        try:
            outcome = await decrypt_document(credentials, document)
        except Exception:  # noqa: BLE001 - do not leak transport details
            return json.dumps(
                {"status": "error", "error": "Failed to reach the DRM API."},
                ensure_ascii=False,
            )

        if not isinstance(outcome, DecryptionSuccess):
            return json.dumps(
                {"status": "failed", "upstream_status": outcome.status, "body": outcome.body},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "status": "success",
                "filename": filename,
                "content_type": outcome.content_type,
                "size": len(outcome.body),
                "content_base64": base64.b64encode(outcome.body).decode("ascii"),
            },
            ensure_ascii=False,
        )

    @mcp.tool(
        name="preprocess_hwp",
        title="Preprocess HWP/HWPX",
        description=(
            "Clean and structure an HWP/HWPX document for AI consumption. Input: "
            "'file_base64' (base64 of the .hwp/.hwpx bytes) and 'filename' (must end "
            "with .hwp or .hwpx). Returns a JSON string with cleaned Markdown and "
            "block metadata (headings/paragraphs/tables)."
        ),
    )
    async def preprocess_hwp(file_base64: str, filename: str) -> str:
        raw = _decode_base64(file_base64)
        if raw is None:
            return json.dumps(
                {"status": "error", "error": "file_base64 is not valid base64."},
                ensure_ascii=False,
            )
        try:
            record = preprocess_bytes(raw, filename)
        except Exception as exc:  # noqa: BLE001
            return json.dumps(
                {"status": "error", "error": str(exc)}, ensure_ascii=False
            )

        markdown = blocks_to_markdown(Path(filename).stem, record["blocks"])
        return json.dumps(
            {
                "status": "success",
                "filename": record["source_file"],
                "format": record["format"],
                "extraction_method": record["extraction_method"],
                "char_count": record["char_count"],
                "block_counts": record["block_counts"],
                "markdown": markdown,
            },
            ensure_ascii=False,
        )

    @mcp.tool(
        name="decrypt_and_preprocess",
        title="Decrypt & Preprocess HWP/HWPX",
        description=(
            "One-shot pipeline: decrypt a DRM-protected HWP/HWPX file then clean and "
            "structure it for AI. Input: 'file_base64' (base64 of the encrypted bytes) "
            "and 'filename' (.hwp/.hwpx). Returns a JSON string with cleaned Markdown "
            "and block metadata. Requires DRM_* env config."
        ),
    )
    async def decrypt_and_preprocess(file_base64: str, filename: str) -> str:
        credentials = load_drm_credentials()
        if not credentials.is_configured:
            return json.dumps(
                {"status": "error", "error": "DRM is not configured (set DRM_* env vars)."},
                ensure_ascii=False,
            )

        raw = _decode_base64(file_base64)
        if raw is None:
            return json.dumps(
                {"status": "error", "error": "file_base64 is not valid base64."},
                ensure_ascii=False,
            )

        document = EncryptedDocument(
            buffer=raw, filename=filename, content_type="application/octet-stream"
        )
        try:
            outcome = await decrypt_document(credentials, document)
        except Exception:  # noqa: BLE001
            return json.dumps(
                {"status": "error", "stage": "decrypt", "error": "Failed to reach the DRM API."},
                ensure_ascii=False,
            )

        if not isinstance(outcome, DecryptionSuccess):
            return json.dumps(
                {
                    "status": "failed",
                    "stage": "decrypt",
                    "upstream_status": outcome.status,
                    "body": outcome.body,
                },
                ensure_ascii=False,
            )

        try:
            record = preprocess_bytes(outcome.body, filename)
        except Exception as exc:  # noqa: BLE001
            return json.dumps(
                {"status": "error", "stage": "preprocess", "error": str(exc)},
                ensure_ascii=False,
            )

        markdown = blocks_to_markdown(Path(filename).stem, record["blocks"])
        return json.dumps(
            {
                "status": "success",
                "filename": record["source_file"],
                "format": record["format"],
                "extraction_method": record["extraction_method"],
                "char_count": record["char_count"],
                "block_counts": record["block_counts"],
                "markdown": markdown,
            },
            ensure_ascii=False,
        )

    return mcp

