"""Test 3 — Entra ID login end-to-end (browser).

Boots the real app (``python -m src.main``) with the test UI enabled, drives a
headless Chromium to ``/auth-ui``, clicks "Sign in", and asserts the browser is
redirected to the Microsoft identity platform authorize endpoint with the
correct client, redirect URI, scope and PKCE parameters.

The test auto-skips when Playwright (or its Chromium browser) is unavailable:
    pip install playwright && python -m playwright install chromium
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

playwright_sync = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed"
)

APP_DIR = Path(__file__).resolve().parents[1]
TENANT_ID = "11111111-1111-1111-1111-111111111111"
CLIENT_ID = "22222222-2222-2222-2222-222222222222"

_AUTHORIZE = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/authorize"
_OIDC_METADATA = {
    "token_endpoint": f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
    "authorization_endpoint": _AUTHORIZE,
    "issuer": f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
    "end_session_endpoint": f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/logout",
    "jwks_uri": f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys",
    "response_modes_supported": ["query", "fragment", "form_post"],
    "response_types_supported": ["code", "id_token", "code id_token"],
    "scopes_supported": ["openid", "profile", "email", "offline_access"],
    "subject_types_supported": ["pairwise"],
    "id_token_signing_alg_values_supported": ["RS256"],
    "code_challenge_methods_supported": ["plain", "S256"],
}
_INSTANCE_DISCOVERY = {
    "tenant_discovery_endpoint": (
        f"https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration"
    ),
    "api-version": "1.1",
    "metadata": [
        {
            "preferred_network": "login.microsoftonline.com",
            "preferred_cache": "login.windows.net",
            "aliases": [
                "login.microsoftonline.com",
                "login.windows.net",
                "login.microsoft.com",
                "sts.windows.net",
            ],
        }
    ],
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(base_url: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/health", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.3)
    return False


@pytest.fixture(scope="module")
def live_server():
    port = _free_port()
    env = {
        **os.environ,
        "PORT": str(port),
        "ENABLE_TEST_UI": "1",
        "AUTH_TENANT_ID": TENANT_ID,
        "AUTH_CLIENT_ID": CLIENT_ID,
        "DISABLE_AUTO_UPDATE": "true",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.main"],
        cwd=str(APP_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        if not _wait_for_health(base_url):
            proc.terminate()
            out = b""
            with contextlib.suppress(Exception):
                out = proc.stdout.read() if proc.stdout else b""
            pytest.skip(f"app server did not become healthy:\n{out.decode(errors='replace')}")
        yield base_url
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)


def test_entra_login_redirects_to_microsoft(live_server: str):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 - browser not installed
            pytest.skip(f"chromium not available (run 'playwright install chromium'): {exc}")

        try:
            page = browser.new_page()

            # Fully offline + deterministic: stub MSAL's discovery/metadata calls
            # so the SPA builds and navigates to the authorize endpoint even with
            # a fake tenant, then capture that authorize navigation.
            captured: dict = {}

            def handle_ms(route):
                request = route.request
                url = request.url
                if "/discovery/instance" in url:
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(_INSTANCE_DISCOVERY),
                    )
                elif "/.well-known/openid-configuration" in url:
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(_OIDC_METADATA),
                    )
                elif request.is_navigation_request() and "/oauth2/v2.0/authorize" in url:
                    captured["url"] = url
                    route.fulfill(status=200, content_type="text/html", body="<html>stub</html>")
                else:
                    route.fulfill(status=200, content_type="application/json", body="{}")

            page.route("**login.microsoftonline.com/**", handle_ms)

            page.goto(live_server + "/auth-ui", wait_until="load")
            page.click("#loginBtn")

            for _ in range(100):
                if "url" in captured:
                    break
                page.wait_for_timeout(100)

            assert "url" in captured, "no navigation to the Microsoft authorize endpoint"
            url = captured["url"]
            assert "login.microsoftonline.com" in url
            assert TENANT_ID in url

            query = parse_qs(urlparse(url).query)
            assert query.get("client_id") == [CLIENT_ID]
            assert query.get("response_type") == ["code"]
            assert query.get("redirect_uri", [""])[0].endswith("/auth-ui")
            assert "access_as_user" in query.get("scope", [""])[0]
            # PKCE must be present for the SPA authorization-code flow.
            assert query.get("code_challenge_method") == ["S256"]
            assert query.get("code_challenge", [""])[0]
        finally:
            browser.close()


def test_auth_ui_config_endpoint(live_server: str):
    import json

    with urllib.request.urlopen(live_server + "/auth-ui/config", timeout=5) as resp:
        cfg = json.loads(resp.read().decode())

    assert cfg["tenantId"] == TENANT_ID
    assert cfg["clientId"] == CLIENT_ID
    assert cfg["scope"] == f"api://{CLIENT_ID}/access_as_user"
