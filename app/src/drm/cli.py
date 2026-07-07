"""DRM decryption CLI.

Usage:
    python -m src.drm.cli <encrypted-file> [--out <path>]

Reads DRM credentials from the environment (see ``DrmCredentials``), signs the
request server-side, forwards the file to the DRM/MIP decrypt API, and writes
the decrypted bytes to ``--out`` (default: ``<file>.decrypted``).

Exit codes: 0 success, 2 not configured, 3 no input, 1 decrypt/transport error.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .credentials import DrmCredentials, load_drm_credentials
from .decryption_client import (
    DecryptionOutcome,
    DecryptionSuccess,
    EncryptedDocument,
    decrypt_document,
)


def parse_cli(argv: list[str]) -> tuple[str | None, str | None]:
    """Parse args. Returns (input path or None, output path or None)."""
    target = None
    out = None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("--out", "-o"):
            i += 1
            if i < len(argv):
                out = argv[i]
        elif a.startswith("--out="):
            out = a.split("=", 1)[1]
        elif target is None:
            target = a
        i += 1
    return target, out


async def decrypt_path(
    credentials: DrmCredentials, input_path: Path
) -> DecryptionOutcome:
    """Read ``input_path`` and call the DRM decrypt API, returning the outcome."""
    document = EncryptedDocument(
        buffer=input_path.read_bytes(),
        filename=input_path.name,
        content_type="application/octet-stream",
    )
    return await decrypt_document(credentials, document)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    target_arg, out_arg = parse_cli(argv)

    if target_arg is None:
        print("Specify an encrypted file to decrypt.")
        print("  e.g.  python -m src.drm.cli ./secret.hwp --out ./secret.plain")
        return 3

    input_path = Path(target_arg)
    if not input_path.is_file():
        print(f"Input file not found: {input_path}")
        return 3

    credentials = load_drm_credentials()
    if not credentials.is_configured:
        print(
            "DRM is not configured. Set DRM_CLIENT_ID, DRM_KEY_ID, DRM_SECRET_KEY, "
            "DRM_USER_EMAIL and DRM_USER_LOGINID."
        )
        return 2

    output_path = Path(out_arg) if out_arg else input_path.with_suffix(
        input_path.suffix + ".decrypted"
    )

    try:
        outcome = asyncio.run(decrypt_path(credentials, input_path))
    except Exception as error:  # noqa: BLE001 - translate any transport failure
        print(f"Failed to reach the DRM API: {error}")
        return 1

    if not isinstance(outcome, DecryptionSuccess):
        print(f"DRM API returned an error (status {outcome.status}): {outcome.body}")
        return 1

    output_path.write_bytes(outcome.body)
    print(f"[OK] decrypted {input_path.name} -> {output_path} ({len(outcome.body)} bytes)")
    print(f"     content-type: {outcome.content_type}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
