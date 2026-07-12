"""Tests for app-level authentication middleware in src.main."""

from __future__ import annotations

import json
import logging
import time

from starlette.requests import Request
from fastapi.testclient import TestClient

from src.identity.auth_middleware import _required_scopes_for, authenticate_request
from src.main import app
from tests.auth_test_support import (
    build_signing_material,
    local_jwks_server,
    sign_token,
    temporary_env,
)


def _request(method: str, path: str, authorization: str | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 1234),
            "http_version": "1.1",
        }
    )


def test_health_endpoint_is_not_protected():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_rejects_invalid_token_via_middleware():
    with temporary_env(
        AUTH_TENANT_ID="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        AUTH_CLIENT_ID="11111111-2222-3333-4444-555555555555",
    ):
        failure = authenticate_request(_request("POST", "/upload", "Bearer invalid.token.value"))
    assert failure is not None
    assert failure.status_code == 401


def test_upload_passes_middleware_with_real_signed_token():
    tenant_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    client_id = "11111111-2222-3333-4444-555555555555"
    private_key, jwks = build_signing_material()
    kid = jwks["keys"][0]["kid"]
    claims = {
        "aud": client_id,
        "iss": f"https://sts.windows.net/{tenant_id}/",
        "exp": int(time.time()) + 600,
        "nbf": int(time.time()) - 10,
        "scp": "access_as_user",
        "name": "Upload User",
        "unique_name": "upload.user@contoso.com",
        "appid": "22cc22cc-22cc-22cc-22cc-22cc22cc22cc",
        "oid": "object-1",
    }

    with local_jwks_server(jwks) as jwks_uri:
        with temporary_env(
            AUTH_TENANT_ID=tenant_id,
            AUTH_CLIENT_ID=client_id,
            AUTH_JWKS_URI=jwks_uri,
        ):
            token = sign_token(private_key, claims, kid)
            failure = authenticate_request(_request("POST", "/upload", f"Bearer {token}"))
    assert failure is None

    with local_jwks_server(jwks) as jwks_uri:
        with temporary_env(
            AUTH_TENANT_ID=tenant_id,
            AUTH_CLIENT_ID=client_id,
            AUTH_JWKS_URI=jwks_uri,
        ):
            token = sign_token(private_key, claims, kid)
            client = TestClient(app)
            response = client.post("/upload", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400
    assert "No file uploaded" in response.json()["error"]


def test_mcp_uses_copilot_scope_candidates():
    request = _request("POST", "/mcp")
    assert _required_scopes_for(request) == [
        "access_as_user",
        "CopilotStudio.AgentNodes.Invoke",
    ]


def test_mcp_accepts_raw_token_with_copilot_scope():
    tenant_id = "d0a0ff17-cf70-4fc6-b2b9-ad659ff82b30"
    client_id = "11111111-2222-3333-4444-555555555555"
    payload = {
        "aud": "https://api.powerplatform.com",
        "iss": f"https://sts.windows.net/{tenant_id}/",
        "exp": int(time.time()) + 900,
        "nbf": int(time.time()) - 30,
        "scp": "CopilotStudio.AgentNodes.Invoke",
        "oid": "oid-1",
        "name": "Copilot User",
        "unique_name": "copilot.user@contoso.com",
        "appid": "33dd33dd-33dd-33dd-33dd-33dd33dd33dd",
    }
    raw = f'Bearer {json.dumps({"typ": "JWT", "alg": "RS256"})}.{json.dumps(payload)}.[Signature]'

    request = _request("POST", "/mcp", raw)
    with temporary_env(AUTH_TENANT_ID=tenant_id, AUTH_CLIENT_ID=client_id):
        failure = authenticate_request(request)
    assert failure is None


def test_middleware_stores_required_identity_fields():
    tenant_id = "d0a0ff17-cf70-4fc6-b2b9-ad659ff82b30"
    client_id = "11111111-2222-3333-4444-555555555555"
    payload = {
        "aud": "https://api.powerplatform.com",
        "iss": f"https://sts.windows.net/{tenant_id}/",
        "exp": int(time.time()) + 900,
        "nbf": int(time.time()) - 30,
        "scp": "CopilotStudio.AgentNodes.Invoke",
        "oid": "oid-1",
        "name": "Copilot User",
        "unique_name": "copilot.user@contoso.com",
        "appid": "33dd33dd-33dd-33dd-33dd-33dd33dd33dd",
    }
    raw = f'Bearer {json.dumps({"typ": "JWT", "alg": "RS256"})}.{json.dumps(payload)}.[Signature]'
    request = _request("POST", "/mcp", raw)

    with temporary_env(AUTH_TENANT_ID=tenant_id, AUTH_CLIENT_ID=client_id):
        failure = authenticate_request(request)
    assert failure is None
    identity = request.state.caller_identity
    assert identity["name"] == "Copilot User"
    assert identity["unique_name"] == "copilot.user@contoso.com"
    assert identity["appid"] == "33dd33dd-33dd-33dd-33dd-33dd33dd33dd"


def test_auth_failure_logs_include_claim_snapshot(caplog):
    tenant_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    client_id = "11111111-2222-3333-4444-555555555555"
    private_key, jwks = build_signing_material()
    kid = jwks["keys"][0]["kid"]
    claims = {
        "aud": client_id,
        "iss": f"https://sts.windows.net/{tenant_id}/",
        "exp": int(time.time()) + 600,
        "nbf": int(time.time()) - 10,
        "scp": "User.Read",
        "name": "Upload User",
        "unique_name": "upload.user@contoso.com",
        "appid": "44ee44ee-44ee-44ee-44ee-44ee44ee44ee",
        "oid": "object-1",
    }
    with local_jwks_server(jwks) as jwks_uri:
        with temporary_env(
            AUTH_TENANT_ID=tenant_id,
            AUTH_CLIENT_ID=client_id,
            AUTH_JWKS_URI=jwks_uri,
        ):
            token = sign_token(private_key, claims, kid)
            request = _request("POST", "/upload", f"Bearer {token}")
            with caplog.at_level(logging.WARNING, logger="lgup_mcp.auth"):
                failure = authenticate_request(request)
    assert failure is not None
    messages = [record.getMessage() for record in caplog.records]
    assert any("Authentication failed" in message for message in messages)
    assert any("upload.user@contoso.com" in message for message in messages)
    assert any("44ee44ee-44ee-44ee-44ee-44ee44ee44ee" in message for message in messages)
