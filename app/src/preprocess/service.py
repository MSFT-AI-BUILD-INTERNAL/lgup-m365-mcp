"""HWP/HWPX preprocessing service — the callable, import-friendly API.

Wraps the pure extraction/cleaning ``core`` functions with the orchestration
that ``docs/tool/preprocess_hwp.py`` performs (write Markdown + JSON, aggregate
a summary), but as return-values rather than console output so it can be called
from other code:

    from src.preprocess import preprocess_file, preprocess_document, preprocess_path

    record  = preprocess_file(Path("a.hwpx"))                 # in-memory only
    doc     = preprocess_document(Path("a.hwpx"), "out")      # + writes a.md/a.json
    summary = preprocess_path("./folder", "out")             # folder/file + _summary.json
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .core import SUPPORTED_SUFFIXES, blocks_to_markdown, process_file


def preprocess_file(path: str | Path, mip=None) -> dict:
    """Preprocess a single HWP/HWPX file and return its structured record.

    Pure/in-memory: does not write anything. Raises ``RuntimeError`` on failure
    (unsupported format, DRM without a decryptor, empty content, ...).
    """
    return process_file(Path(path), mip)


def preprocess_bytes(data: bytes, filename: str, mip=None) -> dict:
    """Preprocess in-memory HWP/HWPX bytes and return the structured record.

    The extractors need a real file path, so the bytes are written to a temp
    file (extension taken from ``filename``), processed, then cleaned up. The
    returned record's ``source_file`` is restored to the original ``filename``.
    Raises ``RuntimeError`` on failure.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise RuntimeError(f"Unsupported format: {suffix or '(none)'}")

    fd, tmp_name = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_bytes(data)
        record = process_file(tmp_path, mip)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    return {**record, "source_file": Path(filename).name}



def preprocess_document(path: str | Path, out_dir: str | Path, mip=None) -> dict:
    """Preprocess one file and write ``<name>.md`` and ``<name>.json`` to ``out_dir``.

    Returns the record augmented with ``md_path``/``json_path``/``outputs``.
    """
    path = Path(path)
    out_dir = Path(out_dir)
    record = process_file(path, mip)

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    md_path = out_dir / (stem + ".md")
    json_path = out_dir / (stem + ".json")
    md_path.write_text(blocks_to_markdown(stem, record["blocks"]), encoding="utf-8")
    json_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        **record,
        "md_path": str(md_path),
        "json_path": str(json_path),
        "outputs": [md_path.name, json_path.name],
    }


def collect_inputs(target: str | Path | None) -> tuple[list[Path], Path | None]:
    """Resolve the target: a folder -> its hwp/hwpx files; a file -> that file.

    Returns ``(files, base)`` where ``base`` is ``None`` when ``target`` is None.
    """
    if target is None:
        return [], None

    target = Path(target)
    if target.is_dir():
        files = sorted(
            p
            for p in target.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
        )
        return files, target
    if target.is_file():
        return [target], target.parent
    return [], target


def default_output_dir(base: Path) -> Path:
    """Default output directory next to the input (``<base>/outputs``)."""
    return (base if base.is_dir() else base.parent) / "outputs"


def preprocess_path(
    target: str | Path,
    out_dir: str | Path | None = None,
    mip=None,
) -> dict:
    """Preprocess a folder (all hwp/hwpx) or a single file.

    Writes each ``<name>.md`` / ``<name>.json`` plus an aggregate
    ``_summary.json`` into ``out_dir`` (default ``<target>/outputs``), and
    returns the summary dict. Never raises for per-file failures — they are
    recorded in the summary with ``status == "failed"``.
    """
    inputs, base = collect_inputs(target)
    if base is None:
        raise ValueError("target must be an existing folder or file")

    output_dir = Path(out_dir) if out_dir else default_output_dir(base)
    output_dir.mkdir(parents=True, exist_ok=True)

    files: list[dict] = []
    success = 0
    failed = 0

    for path in inputs:
        try:
            doc = preprocess_document(path, output_dir, mip)
        except Exception as exc:  # noqa: BLE001 - keep going per-file
            files.append(
                {"source_file": path.name, "status": "failed", "reason": str(exc)}
            )
            failed += 1
            continue

        files.append(
            {
                "source_file": path.name,
                "status": "success",
                "format": doc["format"],
                "extraction_method": doc["extraction_method"],
                "char_count": doc["char_count"],
                "block_counts": doc["block_counts"],
                "outputs": doc["outputs"],
            }
        )
        success += 1

    summary = {
        "input": str(base),
        "output_dir": str(output_dir),
        "total": len(inputs),
        "success": success,
        "failed": failed,
        "files": files,
    }
    (output_dir / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
