"""Shared pytest fixtures for the test suite.

Tests import the app as ``src.*`` (pyproject sets ``pythonpath = ["."]`` with
the app dir as rootdir), so no path hacking is needed here.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

# A minimal but realistic HWPX section: a heading paragraph, a body paragraph,
# and a 2x2 table. Namespaces are arbitrary — the parser strips them.
_SECTION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p><hp:run><hp:t>제 1 조 목적</hp:t></hp:run></hp:p>
  <hp:p><hp:run><hp:t>이 문서는 전처리 테스트를 위한 예시 본문입니다.</hp:t></hp:run></hp:p>
  <hp:tbl>
    <hp:tr>
      <hp:tc><hp:p><hp:run><hp:t>항목</hp:t></hp:run></hp:p></hp:tc>
      <hp:tc><hp:p><hp:run><hp:t>값</hp:t></hp:run></hp:p></hp:tc>
    </hp:tr>
    <hp:tr>
      <hp:tc><hp:p><hp:run><hp:t>가격</hp:t></hp:run></hp:p></hp:tc>
      <hp:tc><hp:p><hp:run><hp:t>1000</hp:t></hp:run></hp:p></hp:tc>
    </hp:tr>
  </hp:tbl>
</hs:sec>
"""


def _write_hwpx(path: Path) -> Path:
    """Write a valid (ZIP-based) .hwpx file with one content section."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Minimal container hint files (not parsed, but make it look real).
        zf.writestr("mimetype", "application/hwp+zip")
        zf.writestr("Contents/section0.xml", _SECTION_XML)
    path.write_bytes(buffer.getvalue())
    return path


@pytest.fixture
def sample_hwpx(tmp_path: Path) -> Path:
    """Create a temporary, parseable .hwpx file and return its path."""
    return _write_hwpx(tmp_path / "sample.hwpx")


@pytest.fixture
def drm_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Set a full set of DRM credentials in the environment for CLI tests."""
    values = {
        "DRM_HOST": "drm.example.test",
        "DRM_CLIENT_ID": "test-client",
        "DRM_KEY_ID": "test-key",
        "DRM_SECRET_KEY": "test-secret",
        "DRM_USER_EMAIL": "user@example.test",
        "DRM_USER_LOGINID": "user01",
    }
    for key, val in values.items():
        monkeypatch.setenv(key, val)
    return values
