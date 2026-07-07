"""Shared kernel: process-wide server identity and runtime configuration.

Kept intentionally small and stable so every bounded context can depend on it.
"""

from __future__ import annotations

import os
from pathlib import Path

SERVER_NAME = "lgup-ax-mcp-server"
SERVER_VERSION = "1.0.0"

# Port is configurable so the Bicep-deployed Container App can inject containerPort (default 8080).
PORT = int(os.environ.get("PORT", "8080"))


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# The browser test UIs (/auth-ui, /drm-ui, ...) are a DEV/TEST-ONLY frontend.
# They are NOT part of the production API/MCP surface and stay disabled unless
# explicitly enabled. Real clients call the API (/drm/decrypt) and MCP (/mcp).
ENABLE_TEST_UI = _env_flag("ENABLE_TEST_UI", default=False)

# The MSAL browser UMD bundle is vendored locally so the test UIs work without an
# external CDN (which is often blocked on corporate networks).
STATIC_DIR = Path(__file__).resolve().parent.parent / "test_ui" / "static"
MSAL_BROWSER_PATH = STATIC_DIR / "msal-browser.min.js"
