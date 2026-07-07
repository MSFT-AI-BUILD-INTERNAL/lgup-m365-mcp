"""Test 1 — CLI preprocessing of HWP / HWPX files.

Exercises the ``python -m src.preprocess`` pipeline (ported from
``docs/tool/preprocess_hwp.py``):
  * HWPX is parsed for real with the standard library.
  * HWP extraction (which needs pyhwp) is monkeypatched so the cleaning +
    serialization path is covered without the external binary.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.preprocess import cli
from src.preprocess import core

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_cli_preprocesses_hwpx(sample_hwpx: Path, tmp_path: Path):
    out_dir = tmp_path / "out"

    exit_code = cli.main(["preprocess", str(sample_hwpx), "--out", str(out_dir)])

    assert exit_code == 0

    md_path = out_dir / "sample.md"
    json_path = out_dir / "sample.json"
    summary_path = out_dir / "_summary.json"
    assert md_path.is_file()
    assert json_path.is_file()
    assert summary_path.is_file()

    record = json.loads(json_path.read_text(encoding="utf-8"))
    assert record["format"] == "hwpx"
    assert record["block_counts"]["heading"] == 1  # "제 1 조 목적" promoted
    assert record["block_counts"]["paragraph"] == 1
    assert record["block_counts"]["table"] == 1

    types = [b["type"] for b in record["blocks"]]
    assert types == ["heading", "paragraph", "table"]

    table = next(b for b in record["blocks"] if b["type"] == "table")
    assert table["rows"] == [["항목", "값"], ["가격", "1000"]]

    md = md_path.read_text(encoding="utf-8")
    assert "## 제 1 조 목적" in md
    assert "| 항목 | 값 |" in md
    assert "| 가격 | 1000 |" in md

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["total"] == 1
    assert summary["success"] == 1
    assert summary["failed"] == 0


def test_cli_preprocesses_hwp_with_mocked_extractor(
    tmp_path: Path, monkeypatch
):
    # A real-looking .hwp (correct OLE magic so it is not flagged as DRM).
    hwp_path = tmp_path / "doc.hwp"
    hwp_path.write_bytes(core.OLE_MAGIC + b"\x00" * 512)

    sample_text = "제 2 장 범위\n본문 첫 문단입니다.\n\n두 번째 문단.\n"
    monkeypatch.setattr(
        core, "extract_hwp", lambda p: (sample_text, "mock hwp5txt")
    )

    out_dir = tmp_path / "out"
    exit_code = cli.main(["preprocess", str(hwp_path), "--out", str(out_dir)])

    assert exit_code == 0
    record = json.loads((out_dir / "doc.json").read_text(encoding="utf-8"))
    assert record["format"] == "hwp"
    assert record["extraction_method"] == "mock hwp5txt"
    assert record["block_counts"]["heading"] == 1  # "제 2 장 범위"
    assert record["block_counts"]["paragraph"] == 2


def test_cli_reports_failure_for_unreadable_hwpx(tmp_path: Path):
    # A .hwpx whose bytes are not a ZIP -> flagged as DRM-encrypted, no mip -> fail.
    bad = tmp_path / "broken.hwpx"
    bad.write_bytes(b"not-a-zip-file")

    out_dir = tmp_path / "out"
    exit_code = cli.main(["preprocess", str(bad), "--out", str(out_dir)])

    assert exit_code == 1
    summary = json.loads((out_dir / "_summary.json").read_text(encoding="utf-8"))
    assert summary["success"] == 0
    assert summary["failed"] == 1
    assert summary["files"][0]["status"] == "failed"


def test_cli_without_target_returns_error(capsys):
    assert cli.main(["preprocess"]) == 1


def test_cli_preprocesses_real_hwpx_fixture(tmp_path: Path):
    # A real (public) HWPX trimmed to 3 pages, parsed with the stdlib path.
    fixture = FIXTURES / "sample_bid_plan_3pages.hwpx"
    assert fixture.is_file()

    out_dir = tmp_path / "out"
    exit_code = cli.main(["preprocess", str(fixture), "--out", str(out_dir)])

    assert exit_code == 0
    record = json.loads((out_dir / (fixture.stem + ".json")).read_text(encoding="utf-8"))
    assert record["format"] == "hwpx"
    assert record["char_count"] > 0
    assert record["block_counts"]["paragraph"] >= 1

    md = (out_dir / (fixture.stem + ".md")).read_text(encoding="utf-8")
    assert "발주계획" in md


@pytest.mark.skipif(
    importlib.util.find_spec("hwp5") is None, reason="pyhwp not installed"
)
def test_hwp_extractor_available():
    # With pyhwp installed, legacy .hwp extraction is wired up (both formats work).
    assert core.find_hwp5txt() is not None


def test_callable_api(sample_hwpx: Path, tmp_path: Path):
    from src.preprocess import preprocess_document, preprocess_file, preprocess_path

    # In-memory: no files written.
    record = preprocess_file(sample_hwpx)
    assert record["format"] == "hwpx"
    assert record["block_counts"]["table"] == 1

    # Single document: writes md/json and reports their paths.
    out_dir = tmp_path / "doc"
    doc = preprocess_document(sample_hwpx, out_dir)
    assert (out_dir / "sample.md").is_file()
    assert (out_dir / "sample.json").is_file()
    assert doc["outputs"] == ["sample.md", "sample.json"]

    # Path (file or folder): writes _summary.json and returns the summary.
    out_dir2 = tmp_path / "path"
    summary = preprocess_path(sample_hwpx, out_dir2)
    assert summary["total"] == 1
    assert summary["success"] == 1
    assert summary["failed"] == 0
    assert (out_dir2 / "_summary.json").is_file()
