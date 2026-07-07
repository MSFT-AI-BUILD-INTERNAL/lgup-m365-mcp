"""Storage context — configuration loaded from environment variables.

The storage account is provisioned externally; the app only needs connection
details (account URL or connection string) and the container name.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class StorageSettings:
    account_url: str
    connection_string: str
    container_name: str

    @property
    def is_configured(self) -> bool:
        """True when at least one usable credential source is present."""
        return bool(self.account_url or self.connection_string)


def load_storage_settings() -> StorageSettings:
    return StorageSettings(
        account_url=os.environ.get("AZURE_STORAGE_ACCOUNT_URL", ""),
        connection_string=os.environ.get("AZURE_STORAGE_CONNECTION_STRING", ""),
        container_name=os.environ.get("AZURE_STORAGE_CONTAINER", "uploads"),
    )
