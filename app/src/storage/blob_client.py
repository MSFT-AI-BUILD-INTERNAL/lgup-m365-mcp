"""Storage context — Blob Storage upload client.

Abstracts Azure Blob SDK operations so the rest of the application is not
coupled to the SDK directly. Uses ``DefaultAzureCredential`` (Managed Identity
on Azure Container Apps) when only an account URL is provided, falling back to a
connection string for local development.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from .settings import StorageSettings


@dataclass(frozen=True)
class BlobUploadResult:
    blob_name: str
    container: str
    url: str
    content_type: str
    size: int

    def to_dict(self) -> dict[str, str | int]:
        """Serialize to a JSON-friendly dict for HTTP responses."""
        return {
            "name": self.blob_name,
            "container": self.container,
            "url": self.url,
            "content_type": self.content_type,
            "size": self.size,
        }


def _build_service_client(settings: StorageSettings) -> BlobServiceClient:
    """Create a BlobServiceClient from the best available credential."""
    if settings.connection_string:
        return BlobServiceClient.from_connection_string(settings.connection_string)
    return BlobServiceClient(settings.account_url, credential=DefaultAzureCredential())


def _generate_blob_name(original_filename: str) -> str:
    """Generate a unique blob name preserving the original extension."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    unique = uuid.uuid4().hex[:8]
    return f"{timestamp}/{unique}-{original_filename}"


def _upload_blob_sync(
    settings: StorageSettings,
    data: bytes,
    filename: str,
    content_type: str,
) -> BlobUploadResult:
    """Synchronous upload — runs inside a thread to avoid blocking the loop."""
    service_client = _build_service_client(settings)
    container_client = service_client.get_container_client(settings.container_name)

    blob_name = _generate_blob_name(filename)
    blob_client = container_client.get_blob_client(blob_name)

    blob_content_settings = ContentSettings(content_type=content_type)
    blob_client.upload_blob(data, overwrite=True, content_settings=blob_content_settings)

    return BlobUploadResult(
        blob_name=blob_name,
        container=settings.container_name,
        url=blob_client.url,
        content_type=content_type,
        size=len(data),
    )


async def upload_blob(
    settings: StorageSettings,
    data: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
) -> BlobUploadResult:
    """Upload a file to Azure Blob Storage and return upload metadata.

    The synchronous Azure SDK call is offloaded to a thread so the FastAPI
    event loop is not blocked during network I/O.
    """
    return await asyncio.to_thread(
        _upload_blob_sync, settings, data, filename, content_type
    )
