"""Unit tests for the Storage bounded context.

Covers:
  - StorageSettings loading & validation
  - BlobUploadResult serialization
  - blob_client upload flow (mocked Azure SDK)
  - routes.py upload endpoint (mocked blob + DRM)
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.storage.blob_client import (
    BlobUploadResult,
    _generate_blob_name,
    _upload_blob_sync,
)
from src.storage.settings import StorageSettings, load_storage_settings


# ---------------------------------------------------------------------------
# StorageSettings
# ---------------------------------------------------------------------------


class TestStorageSettings:
    def test_is_configured_with_account_url(self):
        s = StorageSettings(
            account_url="https://x.blob.core.windows.net",
            connection_string="",
            container_name="uploads",
        )
        assert s.is_configured is True

    def test_is_configured_with_connection_string(self):
        s = StorageSettings(
            account_url="",
            connection_string="DefaultEndpointsProtocol=https;...",
            container_name="uploads",
        )
        assert s.is_configured is True

    def test_not_configured_when_empty(self):
        s = StorageSettings(account_url="", connection_string="", container_name="uploads")
        assert s.is_configured is False

    def test_load_from_env(self, monkeypatch):
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://acc.blob.core.windows.net")
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "connstr")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "mycontainer")

        settings = load_storage_settings()
        assert settings.account_url == "https://acc.blob.core.windows.net"
        assert settings.connection_string == "connstr"
        assert settings.container_name == "mycontainer"

    def test_load_defaults(self, monkeypatch):
        monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
        monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
        monkeypatch.delenv("AZURE_STORAGE_CONTAINER", raising=False)

        settings = load_storage_settings()
        assert settings.account_url == ""
        assert settings.connection_string == ""
        assert settings.container_name == "uploads"


# ---------------------------------------------------------------------------
# BlobUploadResult
# ---------------------------------------------------------------------------


class TestBlobUploadResult:
    def test_to_dict(self):
        result = BlobUploadResult(
            blob_name="20260101-120000/abc12345-test.hwp",
            container="uploads",
            url="https://acc.blob.core.windows.net/uploads/20260101-120000/abc12345-test.hwp",
            content_type="application/octet-stream",
            size=1024,
        )
        d = result.to_dict()
        assert d == {
            "name": "20260101-120000/abc12345-test.hwp",
            "container": "uploads",
            "url": "https://acc.blob.core.windows.net/uploads/20260101-120000/abc12345-test.hwp",
            "content_type": "application/octet-stream",
            "size": 1024,
        }


# ---------------------------------------------------------------------------
# blob_client internals
# ---------------------------------------------------------------------------


class TestGenerateBlobName:
    def test_preserves_filename(self):
        name = _generate_blob_name("report.pdf")
        assert name.endswith("-report.pdf")

    def test_includes_timestamp_prefix(self):
        name = _generate_blob_name("file.txt")
        # Format: YYYYMMDD-HHMMSS/{uuid8}-file.txt
        parts = name.split("/")
        assert len(parts) == 2
        assert len(parts[0]) == 15  # YYYYMMDD-HHMMSS

    def test_unique_per_call(self):
        a = _generate_blob_name("same.txt")
        b = _generate_blob_name("same.txt")
        assert a != b


class TestUploadBlobSync:
    def test_calls_azure_sdk_correctly(self):
        mock_blob_client = MagicMock()
        mock_blob_client.url = "https://acc.blob.core.windows.net/uploads/blob"
        mock_blob_client.upload_blob = MagicMock()

        mock_container_client = MagicMock()
        mock_container_client.get_blob_client = MagicMock(return_value=mock_blob_client)

        mock_service_client = MagicMock()
        mock_service_client.get_container_client = MagicMock(
            return_value=mock_container_client
        )

        settings = StorageSettings(
            account_url="",
            connection_string="DefaultEndpointsProtocol=https;AccountName=test",
            container_name="uploads",
        )

        with patch(
            "src.storage.blob_client._build_service_client",
            return_value=mock_service_client,
        ):
            result = _upload_blob_sync(settings, b"hello", "test.txt", "text/plain")

        mock_service_client.get_container_client.assert_called_once_with("uploads")
        mock_blob_client.upload_blob.assert_called_once()
        assert result.size == 5
        assert result.content_type == "text/plain"
        assert result.container == "uploads"
        assert result.url == "https://acc.blob.core.windows.net/uploads/blob"


# ---------------------------------------------------------------------------
# Routes (integration via TestClient)
# ---------------------------------------------------------------------------


def _make_test_app():
    """Build a minimal FastAPI app with the upload router for testing."""
    from src.storage.routes import router

    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


def _valid_auth_header() -> dict[str, str]:
    """Build a Bearer token that passes scope_failure_response.

    The scope guard decodes the JWT payload and checks for 'access_as_user' in
    the scp claim. We craft a valid base64-encoded payload with that scope.
    """
    import base64
    import json

    payload = json.dumps({"scp": "access_as_user"}).encode()
    b64_payload = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    token = f"header.{b64_payload}.signature"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def storage_env(monkeypatch):
    """Set storage + DRM env vars for route tests."""
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=test")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "uploads")
    monkeypatch.setenv("AUTH_TENANT_ID", "tenant-123")
    monkeypatch.setenv("AUTH_CLIENT_ID", "client-456")
    monkeypatch.setenv("DRM_HOST", "drm.test")
    monkeypatch.setenv("DRM_CLIENT_ID", "drm-client")
    monkeypatch.setenv("DRM_KEY_ID", "drm-key")
    monkeypatch.setenv("DRM_SECRET_KEY", "drm-secret")
    monkeypatch.setenv("DRM_USER_EMAIL", "u@test.com")
    monkeypatch.setenv("DRM_USER_LOGINID", "u01")


class TestUploadRoute:
    def test_401_without_auth(self, storage_env):
        client = TestClient(_make_test_app())
        resp = client.post("/upload", files={"file": ("a.txt", b"data", "text/plain")})
        assert resp.status_code == 401

    def test_400_no_file(self, storage_env):
        client = TestClient(_make_test_app())
        resp = client.post("/upload", headers=_valid_auth_header())
        assert resp.status_code == 400
        assert "No file uploaded" in resp.json()["error"]

    def test_503_storage_not_configured(self, monkeypatch):
        monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
        monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
        monkeypatch.setenv("AUTH_TENANT_ID", "t")
        monkeypatch.setenv("AUTH_CLIENT_ID", "c")

        client = TestClient(_make_test_app())
        resp = client.post(
            "/upload",
            headers=_valid_auth_header(),
            files={"file": ("a.txt", b"data", "text/plain")},
        )
        assert resp.status_code == 503
        assert "not configured" in resp.json()["error"]

    def test_success_drm_decrypts(self, storage_env):
        """Full happy path: blob upload succeeds, DRM returns decrypted file."""
        from src.drm.decryption_client import DecryptionSuccess

        fake_blob = BlobUploadResult(
            blob_name="20260101-000000/aaa-test.hwp",
            container="uploads",
            url="https://acc.blob.core.windows.net/uploads/20260101-000000/aaa-test.hwp",
            content_type="application/octet-stream",
            size=10,
        )
        fake_outcome = DecryptionSuccess(
            ok=True,
            content_type="application/pdf",
            disposition='attachment; filename="out.pdf"',
            body=b"DECRYPTED-CONTENT",
        )

        with (
            patch("src.storage.routes.upload_blob", return_value=fake_blob),
            patch("src.storage.routes.decrypt_document", return_value=fake_outcome),
        ):
            client = TestClient(_make_test_app())
            resp = client.post(
                "/upload",
                headers=_valid_auth_header(),
                files={"file": ("test.hwp", b"ENCRYPTED", "application/octet-stream")},
            )

        assert resp.status_code == 200
        assert resp.content == b"DECRYPTED-CONTENT"
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.headers["x-blob-name"] == "20260101-000000/aaa-test.hwp"

    def test_drm_not_configured_returns_blob_only(self, monkeypatch):
        """When DRM is not configured, returns blob metadata with drm=skipped."""
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=t")
        monkeypatch.setenv("AUTH_TENANT_ID", "t")
        monkeypatch.setenv("AUTH_CLIENT_ID", "c")
        # DRM env vars NOT set
        monkeypatch.delenv("DRM_CLIENT_ID", raising=False)
        monkeypatch.delenv("DRM_KEY_ID", raising=False)
        monkeypatch.delenv("DRM_SECRET_KEY", raising=False)
        monkeypatch.delenv("DRM_USER_EMAIL", raising=False)
        monkeypatch.delenv("DRM_USER_LOGINID", raising=False)

        fake_blob = BlobUploadResult(
            blob_name="20260101-000000/bbb-test.hwp",
            container="uploads",
            url="https://acc.blob.core.windows.net/uploads/bbb",
            content_type="application/octet-stream",
            size=5,
        )

        with patch("src.storage.routes.upload_blob", return_value=fake_blob):
            client = TestClient(_make_test_app())
            resp = client.post(
                "/upload",
                headers=_valid_auth_header(),
                files={"file": ("test.hwp", b"data", "application/octet-stream")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["drm"]["status"] == "skipped"
        assert body["blob"]["name"] == "20260101-000000/bbb-test.hwp"

    def test_drm_failure_returns_blob_and_error(self, storage_env):
        """When DRM API returns an error, response includes blob metadata + failure."""
        from src.drm.decryption_client import DecryptionFailure

        fake_blob = BlobUploadResult(
            blob_name="20260101-000000/ccc-test.hwp",
            container="uploads",
            url="https://acc.blob.core.windows.net/uploads/ccc",
            content_type="application/octet-stream",
            size=5,
        )
        fake_outcome = DecryptionFailure(ok=False, status=403, body="forbidden")

        with (
            patch("src.storage.routes.upload_blob", return_value=fake_blob),
            patch("src.storage.routes.decrypt_document", return_value=fake_outcome),
        ):
            client = TestClient(_make_test_app())
            resp = client.post(
                "/upload",
                headers=_valid_auth_header(),
                files={"file": ("test.hwp", b"data", "application/octet-stream")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["drm"]["status"] == "failed"
        assert body["drm"]["upstream_status"] == 403
        assert body["blob"]["name"] == "20260101-000000/ccc-test.hwp"

    def test_blob_upload_exception_returns_502(self, storage_env):
        """When blob upload raises, returns 502 with a generic error (no exception leak)."""
        with patch(
            "src.storage.routes.upload_blob",
            side_effect=RuntimeError("connection timeout"),
        ):
            client = TestClient(_make_test_app())
            resp = client.post(
                "/upload",
                headers=_valid_auth_header(),
                files={"file": ("test.hwp", b"data", "application/octet-stream")},
            )

        assert resp.status_code == 502
        body = resp.json()
        assert body["error"] == "Failed to upload file to Blob Storage."
        # Exception details must not be exposed to the client (CodeQL).
        assert "connection timeout" not in resp.text
        assert "detail" not in body

    def test_drm_exception_returns_502_with_blob_info(self, storage_env):
        """When DRM decrypt raises, returns 502 but still includes blob metadata."""
        fake_blob = BlobUploadResult(
            blob_name="20260101-000000/ddd-test.hwp",
            container="uploads",
            url="https://acc.blob.core.windows.net/uploads/ddd",
            content_type="application/octet-stream",
            size=5,
        )

        with (
            patch("src.storage.routes.upload_blob", return_value=fake_blob),
            patch(
                "src.storage.routes.decrypt_document",
                side_effect=RuntimeError("network error"),
            ),
        ):
            client = TestClient(_make_test_app())
            resp = client.post(
                "/upload",
                headers=_valid_auth_header(),
                files={"file": ("test.hwp", b"data", "application/octet-stream")},
            )

        assert resp.status_code == 502
        body = resp.json()
        assert body["drm"]["status"] == "error"
        assert body["drm"]["detail"] == "DRM decryption request failed."
        # Exception details must not be exposed to the client (CodeQL).
        assert "network error" not in resp.text
        assert body["blob"]["name"] == "20260101-000000/ddd-test.hwp"
