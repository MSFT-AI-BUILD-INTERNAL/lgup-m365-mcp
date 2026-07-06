"""Shared kernel: process-wide server identity and runtime configuration.

Kept intentionally small and stable so every bounded context can depend on it.
"""

from __future__ import annotations

import os
from pathlib import Path

SERVER_NAME = "hanik-mcp-server"
SERVER_VERSION = "1.0.0"

# Port is configurable so the Bicep-deployed Container App can inject containerPort (default 8080).
PORT = int(os.environ.get("PORT", "8080"))

# The MSAL browser UMD bundle is vendored locally so the test UIs work without an
# external CDN (which is often blocked on corporate networks).
STATIC_DIR = Path(__file__).resolve().parent.parent / "presentation" / "static"
MSAL_BROWSER_PATH = STATIC_DIR / "msal-browser.min.js"
