"""Test 2 — CLI file decryption against a mocked DRM API.

Uses ``httpx.MockTransport`` (no extra dependency) so the ``python -m src.drm.cli``
decrypt path is exercised end-to-end: the request is signed and shaped correctly
(normal call) and the mocked plaintext response is written out (response check).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from src.drm import cli as drm_cli


def _install_mock_transport(monkeypatch, handler) -> None:
    """Make ``httpx.AsyncClient(...)`` route through a MockTransport."""
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real_client(transport=transport)
    )


def test_decrypt_cli_success(tmp_path: Path, drm_env, monkeypatch):
    enc = tmp_path / "secret.hwp"
    enc.write_bytes(b"ENCRYPTED-BYTES")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["content"] = request.content
        return httpx.Response(
            200,
            content=b"PLAINTEXT-OK",
            headers={
                "content-type": "application/pdf",
                "content-disposition": 'attachment; filename="secret.pdf"',
            },
        )

    _install_mock_transport(monkeypatch, handler)

    out = tmp_path / "secret.plain"
    exit_code = drm_cli.main(["decrypt", str(enc), "--out", str(out)])

    # Response check: decrypted bytes written out, success exit code.
    assert exit_code == 0
    assert out.read_bytes() == b"PLAINTEXT-OK"

    # Normal-call check: endpoint, signing headers and the uploaded payload.
    assert captured["url"].endswith("/v1/mip/decrypt")
    assert captured["url"].startswith("https://drm.example.test/")
    assert captured["headers"]["x-client-id"] == "test-client"
    assert captured["headers"]["x-key-id"] == "test-key"
    assert captured["headers"]["x-user-email"] == "user@example.test"
    assert captured["headers"]["x-user-loginid"] == "user01"
    assert "x-timestamp" in captured["headers"]
    assert captured["headers"]["authorization"].startswith("SEULGI-HMAC-SHA256-V1 ")
    assert b"ENCRYPTED-BYTES" in captured["content"]


def test_decrypt_cli_upstream_error(tmp_path: Path, drm_env, monkeypatch):
    enc = tmp_path / "secret.hwp"
    enc.write_bytes(b"ENCRYPTED-BYTES")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    _install_mock_transport(monkeypatch, handler)

    out = tmp_path / "secret.plain"
    exit_code = drm_cli.main(["decrypt", str(enc), "--out", str(out)])

    assert exit_code == 1
    assert not out.exists()


def test_decrypt_cli_not_configured(tmp_path: Path, monkeypatch):
    for key in (
        "DRM_CLIENT_ID",
        "DRM_KEY_ID",
        "DRM_SECRET_KEY",
        "DRM_USER_EMAIL",
        "DRM_USER_LOGINID",
    ):
        monkeypatch.delenv(key, raising=False)

    enc = tmp_path / "secret.hwp"
    enc.write_bytes(b"ENCRYPTED-BYTES")

    assert drm_cli.main(["decrypt", str(enc)]) == 2


def test_decrypt_cli_missing_input(tmp_path: Path, drm_env):
    missing = tmp_path / "nope.hwp"
    assert drm_cli.main(["decrypt", str(missing)]) == 3
