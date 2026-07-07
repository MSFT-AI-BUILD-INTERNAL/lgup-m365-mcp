"""HWP/HWPX preprocessing context.

Ports the standalone ``docs/tool/preprocess_hwp.py`` logic into the app as a
reusable package + CLI. Pure, local-only preprocessing (no network calls):

- ``.hwp``  (legacy OLE binary) -> text via pyhwp ``hwp5txt`` (CLI or Python API)
- ``.hwpx`` (ZIP + XML)         -> structured blocks via the standard library

Run as a CLI:  ``python -m src.preprocess <folder|file> [--out <dir>]``
"""

from .core import (
    annotate_headings,
    blocks_to_markdown,
    build_record,
    clean_text_to_blocks,
    extract_hwp,
    extract_hwpx,
    looks_drm_encrypted,
    process_file,
)

__all__ = [
    "annotate_headings",
    "blocks_to_markdown",
    "build_record",
    "clean_text_to_blocks",
    "extract_hwp",
    "extract_hwpx",
    "looks_drm_encrypted",
    "process_file",
]
