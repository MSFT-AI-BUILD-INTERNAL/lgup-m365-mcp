"""Unit tests for raw Copilot Studio token validation."""

from __future__ import annotations

import json
import time

import pytest

from src.identity.entra_token_validator import (
    TokenValidationError,
    validate_entra_access_token,
)
from tests.auth_test_support import (
    build_signing_material,
    local_jwks_server,
    sign_token,
    temporary_env,
)


def _raw_bearer(payload: dict) -> str:
    header = {"typ": "JWT", "alg": "RS256", "kid": "k1"}
    return f"Bearer {json.dumps(header)}.{json.dumps(payload)}.[Signature]"


def test_raw_token_format_is_accepted_for_copilot_scope():
    tenant_id = "d0a0ff17-cf70-4fc6-b2b9-ad659ff82b30"
    client_id = "c33af128-1111-2222-3333-444444444444"

    payload = {
        "aud": "https://api.powerplatform.com",
        "iss": f"https://sts.windows.net/{tenant_id}/",
        "exp": int(time.time()) + 3600,
        "nbf": int(time.time()) - 30,
        "scp": "CopilotStudio.AgentNodes.Invoke",
        "name": "Copilot User",
        "unique_name": "copilot.user@contoso.com",
        "appid": "00aa00aa-00aa-00aa-00aa-00aa00aa00aa",
        "oid": "bce20516-13c4-4603-8a22-6141f1adcf02",
    }

    with temporary_env(AUTH_TENANT_ID=tenant_id, AUTH_CLIENT_ID=client_id):
        claims = validate_entra_access_token(
            _raw_bearer(payload),
            required_scopes=["access_as_user", "CopilotStudio.AgentNodes.Invoke"],
        )
    assert claims["aud"] == "https://api.powerplatform.com"
    assert claims["oid"] == "bce20516-13c4-4603-8a22-6141f1adcf02"


def test_raw_token_rejects_expired_token():
    tenant_id = "d0a0ff17-cf70-4fc6-b2b9-ad659ff82b30"
    client_id = "c33af128-1111-2222-3333-444444444444"

    payload = {
        "aud": "https://api.powerplatform.com",
        "iss": f"https://sts.windows.net/{tenant_id}/",
        "exp": int(time.time()) - 10,
        "scp": "CopilotStudio.AgentNodes.Invoke",
        "name": "Copilot User",
        "unique_name": "copilot.user@contoso.com",
        "appid": "00aa00aa-00aa-00aa-00aa-00aa00aa00aa",
    }

    with temporary_env(AUTH_TENANT_ID=tenant_id, AUTH_CLIENT_ID=client_id):
        with pytest.raises(TokenValidationError) as exc:
            validate_entra_access_token(
                _raw_bearer(payload),
                required_scopes=["CopilotStudio.AgentNodes.Invoke"],
            )
    assert exc.value.status_code == 401
    assert "expired" in exc.value.message.lower()


def test_compact_jwt_is_verified_with_real_jwks():
    tenant_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    client_id = "11111111-2222-3333-4444-555555555555"
    private_key, jwks = build_signing_material()
    kid = jwks["keys"][0]["kid"]

    claims = {
        "aud": client_id,
        "iss": f"https://sts.windows.net/{tenant_id}/",
        "exp": int(time.time()) + 600,
        "nbf": int(time.time()) - 30,
        "scp": "access_as_user",
        "name": "Integration User",
        "unique_name": "integration.user@contoso.com",
        "appid": "11bb11bb-11bb-11bb-11bb-11bb11bb11bb",
        "oid": "abc",
    }

    with local_jwks_server(jwks) as jwks_uri:
        with temporary_env(
            AUTH_TENANT_ID=tenant_id,
            AUTH_CLIENT_ID=client_id,
            AUTH_JWKS_URI=jwks_uri,
        ):
            token = sign_token(private_key, claims, kid)
            validated = validate_entra_access_token(f"Bearer {token}")
    assert validated["oid"] == "abc"


def test_rejects_token_without_required_identity_claims():
    tenant_id = "d0a0ff17-cf70-4fc6-b2b9-ad659ff82b30"
    client_id = "c33af128-1111-2222-3333-444444444444"
    payload = {
        "aud": "https://api.powerplatform.com",
        "iss": f"https://sts.windows.net/{tenant_id}/",
        "exp": int(time.time()) + 3600,
        "nbf": int(time.time()) - 30,
        "scp": "CopilotStudio.AgentNodes.Invoke",
        "name": "Copilot User",
    }
    with temporary_env(AUTH_TENANT_ID=tenant_id, AUTH_CLIENT_ID=client_id):
        with pytest.raises(TokenValidationError) as exc:
            validate_entra_access_token(
                _raw_bearer(payload),
                required_scopes=["CopilotStudio.AgentNodes.Invoke"],
            )
    assert exc.value.status_code == 401
    assert "missing required claim" in (exc.value.www_authenticate or "").lower()
