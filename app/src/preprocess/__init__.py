"""HWP/HWPX preprocessing context.

Ports the standalone ``docs/tool/preprocess_hwp.py`` logic into the app as a
reusable package + CLI. Pure, local-only preprocessing (no network calls):

- ``.hwp``  (legacy OLE binary) -> text via pyhwp ``hwp5txt`` (CLI or Python API)
- ``.hwpx`` (ZIP + XML)         -> structured blocks via the standard library

Callable API (import and use directly):

    from src.preprocess import preprocess_file, preprocess_document, preprocess_path

    record  = preprocess_file("a.hwpx")             # structured record, no writes
    doc     = preprocess_document("a.hwpx", "out")  # + writes a.md / a.json
    summary = preprocess_path("./folder", "out")    # folder/file + _summary.json

Or run as a CLI:  ``python -m src.preprocess <folder|file> [--out <dir>]``
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
from .service import (
    collect_inputs,
    default_output_dir,
    preprocess_bytes,
    preprocess_document,
    preprocess_file,
    preprocess_path,
)

__all__ = [
    # High-level callable API
    "preprocess_file",
    "preprocess_bytes",
    "preprocess_document",
    "preprocess_path",
    "collect_inputs",
    "default_output_dir",
    # Low-level building blocks
    "annotate_headings",
    "blocks_to_markdown",
    "build_record",
    "clean_text_to_blocks",
    "extract_hwp",
    "extract_hwpx",
    "looks_drm_encrypted",
    "process_file",
]
