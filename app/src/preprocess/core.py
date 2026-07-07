"""HWP/HWPX preprocessing core.

Faithful port of the extraction + cleaning + serialization logic from
``docs/tool/preprocess_hwp.py``. Contains no network access and no CLI wiring
(see ``cli.py``); it only turns a document into structured blocks and records.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SUPPORTED_SUFFIXES = (".hwp", ".hwpx")

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"


# =====================================================================
# 1) .hwp (legacy binary) extraction — pyhwp (hwp5txt)
# =====================================================================

def find_hwp5txt() -> str | None:
    """Locate the pyhwp ``hwp5txt`` executable, even when not on PATH."""
    for name in ("hwp5txt", "hwp5txt.exe"):
        found = shutil.which(name)
        if found:
            return found

    script_dirs = []
    for scheme in (None, "nt_user"):
        try:
            if scheme is None:
                script_dirs.append(sysconfig.get_path("scripts"))
            else:
                script_dirs.append(sysconfig.get_path("scripts", scheme=scheme))
        except Exception:
            continue

    for d in script_dirs:
        if not d:
            continue
        for fname in ("hwp5txt.exe", "hwp5txt"):
            cand = Path(d) / fname
            if cand.exists():
                return str(cand)

    return None


def extract_hwp(hwp_path: Path) -> tuple[str, str]:
    """Extract text from a ``.hwp``. Returns (text, method); raises on failure.

    1st: ``hwp5txt`` CLI (most stable across pyhwp versions).
    2nd: pyhwp Python API (fallback).
    """
    errors = []

    exe = find_hwp5txt()
    if exe is not None:
        try:
            proc = subprocess.run([exe, str(hwp_path)], capture_output=True)
            if proc.returncode == 0:
                text = proc.stdout.decode("utf-8", errors="replace")
                if text.strip():
                    return text, f"pyhwp hwp5txt CLI ({exe})"
                errors.append("hwp5txt: empty extraction result")
            else:
                err = proc.stderr.decode("utf-8", errors="replace").strip()
                errors.append(f"hwp5txt failed (returncode={proc.returncode}): {err}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"hwp5txt call error: {exc}")
    else:
        errors.append("hwp5txt executable not found (pyhwp likely not installed)")

    try:
        from hwp5.hwp5txt import TextTransform
        from hwp5.xmlmodel import Hwp5File

        buffer = io.BytesIO()
        hwp5file = Hwp5File(str(hwp_path))
        try:
            TextTransform().transform_hwp5_to_text(hwp5file, buffer)
        finally:
            close = getattr(hwp5file, "close", None)
            if callable(close):
                close()

        text = buffer.getvalue().decode("utf-8", errors="replace")
        if text.strip():
            return text, "pyhwp Python API"
        errors.append("pyhwp API: empty extraction result")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pyhwp API extraction failed: {exc}")

    raise RuntimeError(" / ".join(errors))


# =====================================================================
# 2) .hwpx (ZIP + XML) extraction — standard library only
# =====================================================================

def _local(tag: str) -> str:
    """Strip the ``{namespace}`` from a tag, returning the local name."""
    return tag.rsplit("}", 1)[-1]


def _text_of(elem: ET.Element) -> str:
    """Collect all ``<...t>`` text under ``elem``, skipping ``tbl`` subtrees."""
    parts = []
    tag = _local(elem.tag)
    if tag == "tbl":
        return ""
    if tag == "t" and elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_text_of(child))
    return "".join(parts)


def _table_block(tbl: ET.Element) -> dict:
    """Convert a ``tbl`` element to ``{'type':'table','rows':[[cell,...],...]}``."""
    rows = []
    for tr in tbl:
        if _local(tr.tag) != "tr":
            continue
        cells = []
        for tc in tr:
            if _local(tc.tag) != "tc":
                continue
            cell_text = " ".join(_text_of(tc).split())
            cells.append(cell_text)
        if not cells:
            continue
        rows.append(cells)
    return {"type": "table", "rows": rows}


def _build_blocks(elem: ET.Element, blocks: list[dict]) -> None:
    """Walk the section XML in document order, building paragraph/table blocks."""
    tag = _local(elem.tag)
    if tag == "tbl":
        blocks.append(_table_block(elem))
        return
    if tag == "p":
        txt = _text_of(elem).strip()
        if txt:
            blocks.append({"type": "paragraph", "text": txt})
        return
    for child in elem:
        _build_blocks(child, blocks)


def extract_hwpx(hwpx_path: Path) -> tuple[list[dict], str]:
    """Extract structured paragraph/table blocks from a ``.hwpx``."""
    blocks: list[dict] = []
    with zipfile.ZipFile(hwpx_path) as zf:
        section_names = [
            n for n in zf.namelist() if re.match(r"Contents/section\d+\.xml$", n)
        ]

        if not section_names:
            raise RuntimeError(
                "No Contents/section*.xml inside the HWPX (unexpected format)"
            )

        def section_index(name: str) -> int:
            m = re.search(r"section(\d+)\.xml$", name)
            return int(m.group(1)) if m else 0

        for name in sorted(section_names, key=section_index):
            try:
                root = ET.fromstring(zf.read(name))
            except ET.ParseError as exc:
                raise RuntimeError(f"{name} XML parse failed: {exc}") from exc
            _build_blocks(root, blocks)

    if not blocks:
        raise RuntimeError("No paragraphs/tables extracted (empty body or format diff)")

    return blocks, "stdlib zipfile+xml direct parse"


# =====================================================================
# 3) Text cleaning (for .hwp plain-text output)
# =====================================================================

_HEADING_PATTERNS = [
    re.compile(r"^제\s*\d+\s*[조장절관항]"),
    re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s*[.)·]"),
    re.compile(r"^[【〔\[][^】〕\]]{1,40}[】〕\]]\s*$"),
    re.compile(r"^\d{1,2}\s*[.)]\s*\S"),
    re.compile(r"^[가나다라마바사아자차카타파하]\s*[.)]\s*\S"),
    re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]"),
]


def _control_char_clean(text: str) -> str:
    """Remove broken control chars (keep tab/newline); normalize newlines."""
    text = "".join(
        ch for ch in text if ch in ("\t", "\n") or ord(ch) >= 32 or ch == "\r"
    )
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _looks_like_heading(line: str) -> bool:
    """True for a short line that matches a heading pattern."""
    s = line.strip()
    if not s or len(s) > 60:
        return False
    return any(p.match(s) for p in _HEADING_PATTERNS)


def clean_text_to_blocks(raw: str) -> list[dict]:
    """Clean plain text (.hwp extraction) into paragraph/heading blocks."""
    text = _control_char_clean(raw)
    lines = [ln.rstrip() for ln in text.split("\n")]

    blocks: list[dict] = []
    buf: list[str] = []

    def flush():
        if buf:
            joined = " ".join(seg.strip() for seg in buf if seg.strip())
            if joined:
                blocks.append({"type": "paragraph", "text": joined})
            buf.clear()

    for line in lines:
        if not line.strip():
            flush()
            continue
        if _looks_like_heading(line):
            flush()
            blocks.append({"type": "heading", "text": line.strip()})
            continue
        buf.append(line)

    flush()
    return blocks


def annotate_headings(blocks: list[dict]) -> list[dict]:
    """Promote paragraph blocks that look like headings (mainly the .hwpx path)."""
    out = []
    for b in blocks:
        if b["type"] == "paragraph" and _looks_like_heading(b["text"]):
            out.append({"type": "heading", "text": b["text"].strip()})
            continue
        out.append(b)
    return out


# =====================================================================
# 4) Blocks -> Markdown / structured record
# =====================================================================

def blocks_to_markdown(title: str, blocks: list[dict]) -> str:
    out = [f"# {title}", ""]
    for b in blocks:
        if b["type"] == "heading":
            out.append(f"## {b['text']}")
            out.append("")
            continue
        if b["type"] == "paragraph":
            out.append(b["text"])
            out.append("")
            continue
        if b["type"] != "table":
            continue

        rows = b.get("rows", [])
        if not rows:
            continue

        width = max(len(r) for r in rows)
        norm = [r + [""] * (width - len(r)) for r in rows]

        out.append("| " + " | ".join(c.replace("|", "\\|") for c in norm[0]) + " |")
        out.append("| " + " | ".join(["---"] * width) + " |")
        for r in norm[1:]:
            out.append("| " + " | ".join(c.replace("|", "\\|") for c in r) + " |")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def build_record(src: Path, fmt: str, method: str, blocks: list[dict]) -> dict:
    char_count = sum(
        (
            len(b.get("text", ""))
            if b["type"] != "table"
            else sum(len(c) for row in b.get("rows", []) for c in row)
        )
        for b in blocks
    )

    counts = {
        "heading": sum(1 for b in blocks if b["type"] == "heading"),
        "paragraph": sum(1 for b in blocks if b["type"] == "paragraph"),
        "table": sum(1 for b in blocks if b["type"] == "table"),
    }

    return {
        "source_file": src.name,
        "format": fmt,
        "extraction_method": method,
        "char_count": char_count,
        "block_counts": counts,
        "blocks": blocks,
    }


# =====================================================================
# 5) Per-file processing (DRM detection + extraction + cleaning)
# =====================================================================

def looks_drm_encrypted(path: Path) -> bool:
    """Guess DRM encryption when the file signature is not a valid HWP/HWPX."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return False

    suffix = path.suffix.lower()
    if suffix == ".hwp":
        return not head.startswith(OLE_MAGIC)
    if suffix == ".hwpx":
        return not head.startswith(ZIP_MAGIC)
    return False


def _extract_blocks(work_path: Path, suffix: str) -> tuple[list[dict], str, str]:
    """Extract + clean per suffix. Returns (blocks, method, fmt)."""
    if suffix == ".hwp":
        raw, method = extract_hwp(work_path)
        return clean_text_to_blocks(raw), method, "hwp"
    if suffix == ".hwpx":
        raw_blocks, method = extract_hwpx(work_path)
        return annotate_headings(raw_blocks), method, "hwpx"
    raise RuntimeError(f"Unsupported format: {suffix}")


def process_file(path: Path, mip=None) -> dict:
    """Process one file into a record dict. Raises RuntimeError on failure.

    When the file is DRM-encrypted, it is decrypted with ``mip`` (a client that
    exposes ``decrypt_file(path) -> bytes``) into a temp plaintext file first; if
    ``mip`` is ``None`` a RuntimeError explains that decryption is required.
    """
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise RuntimeError(f"Unsupported format: {suffix}")

    work_path = path
    tmp_path: Path | None = None
    decrypted = False

    if looks_drm_encrypted(path):
        if mip is None:
            raise RuntimeError(
                "Looks like a DRM-protected document; decryption is required "
                "(provide a mip client with decrypt_file(path) -> bytes)."
            )

        data = mip.decrypt_file(path)

        fd, tmp_name = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        tmp_path = Path(tmp_name)
        tmp_path.write_bytes(data)
        work_path = tmp_path
        decrypted = True

    try:
        blocks, method, fmt = _extract_blocks(work_path, suffix)
        if not blocks:
            raise RuntimeError("Empty content after cleaning")

        if decrypted:
            method = "DRM-decrypted (MIP) then " + method

        return build_record(path, fmt, method, blocks)
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
