"""
HWP/HWPX → AI용 자동 전처리 프로그램
====================================
 
목적
----
폴더 안의 HWP(.hwp) / HWPX(.hwpx) 문서를 **한 번에 자동으로** 읽어서,
AI(사내 Copilot · RFP 분석 에이전트 등)가 **읽기 좋은 깨끗한 형태**로
정제한 뒤 저장한다.
 
- "AI 전처리" = **사람이 손대지 않는 자동 정제**다. (LLM 호출이 아님)
- 결과물은 두 가지:
    1) <파일명>.md   : 사람과 AI 둘 다 읽기 좋은 정제 텍스트(Markdown)
    2) <파일명>.json : 에이전트가 쓰기 좋은 구조화 데이터(문단/표/제목)
  그리고 전체 처리 결과를 모은 `_summary.json` 을 함께 만든다.
 
오픈소스 / 사용 방식
--------------------
- `.hwp`  (구형 바이너리)  → 오픈소스 `pyhwp`(hwp5txt) 로 텍스트 추출
- `.hwpx` (신형 ZIP+XML) → 파이썬 표준 라이브러리(zipfile + xml)로 직접 파싱
                            (외부 패키지 불필요)
 
보안 원칙 (반드시 준수)
-----------------------
- 네트워크/클라우드 API 를 **절대 호출하지 않는다.** (관련 모듈 import 도 안 함)
- 로컬 파일만 읽고, 로컬 outputs 폴더에만 쓴다.
- 민감 문서(RFP·계약서)는 외부로 전송하지 않는다.
 
실패 정책
---------
- 한 파일에서 실패해도 프로그램은 중단되지 않고 다음 파일로 진행한다.
- 실패 사유를 콘솔에 출력하고, 마지막에 성공/실패 요약을 표시한다.
- 종료 코드: 처리 대상이 모두 성공 → 0, 하나라도 실패 → 1
 
DRM(보안문서) 연동
------------------
- 이 파일은 "순수 전처리" 로직만 담고 있다. 사내 DRM 복호화 구조(엑셀 리본 +
  VBA + `mip_decrypt` 모듈)는 별도로 관리되며, 여기서는 그 모듈이 있으면
  사용하고 없으면 건너뛰는 형태의 "플러그인 지점"만 남겨 두었다.
- 연동하려면 이 파일과 같은 폴더(또는 PYTHONPATH)에 사내 `mip_decrypt.py`
  (아래 인터페이스를 만족하는 모듈)를 배치하면 된다.
    - `mip_decrypt.load_context(base_dir) -> MipClient | None`
    - `MipClient.decrypt_file(path) -> bytes`  (복호화된 평문 바이트 반환)
- `mip_decrypt` 모듈이 없으면 DRM 문서는 안내 메시지와 함께 건너뛰고,
  나머지 일반 문서는 그대로 전처리한다.
"""
from __future__ import annotations
 
import io
import json
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
 
try:
    import mip_decrypt
except ImportError:
    mip_decrypt = None
 
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
 
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    PROJECT_ROOT = None
    DEFAULT_INPUT_DIR = None
else:
    BASE_DIR = Path(__file__).resolve().parent
    PROJECT_ROOT = BASE_DIR.parents[2]
    DEFAULT_INPUT_DIR = PROJECT_ROOT / "rfp_hwp"
 
DEFAULT_OUTPUT_DIR = BASE_DIR / "outputs"
 
SUPPORTED_SUFFIXES = (".hwp", ".hwpx")
 
 
# =====================================================================
# 1) .hwp (구형 바이너리) 추출 — pyhwp(hwp5txt) 사용
# =====================================================================
 
def find_hwp5txt() -> str | None:
    """pyhwp 의 hwp5txt 실행 파일 경로를 탐색. PATH 에 없어도 찾도록 보강."""
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
    """.hwp 에서 텍스트를 추출. (텍스트, 사용방식) 반환. 실패 시 RuntimeError.
 
    1순위: hwp5txt CLI (subprocess) — pyhwp 버전 간 호환성이 가장 안정적
    2순위: pyhwp Python API (폴백)
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
                errors.append("hwp5txt: 추출 결과가 비어 있음")
            else:
                err = proc.stderr.decode("utf-8", errors="replace").strip()
                errors.append(f"hwp5txt 실행 실패(returncode={proc.returncode}): {err}")
        except Exception as exc:
            errors.append(f"hwp5txt 호출 오류: {exc}")
    else:
        errors.append("hwp5txt 실행 파일을 찾을 수 없음(pyhwp 미설치 가능성)")
 
    try:
        from hwp5.xmlmodel import Hwp5File
        from hwp5.hwp5txt import TextTransform
 
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
        errors.append("pyhwp API: 추출 결과가 비어 있음")
    except Exception as exc:
        errors.append(f"pyhwp API 추출 실패: {exc}")
 
    raise RuntimeError(" / ".join(errors))
 
 
# =====================================================================
# 2) .hwpx (신형 ZIP+XML) 추출 — 표준 라이브러리만 사용
# =====================================================================
 
def _local(tag: str) -> str:
    """'{네임스페이스}태그' 에서 네임스페이스를 떼고 태그 이름만 반환."""
    return tag.rsplit("}", 1)[-1]
 
 
def _text_of(elem: ET.Element) -> str:
    """elem 아래의 모든 텍스트(<...t>)를 모아 문자열로. 표(tbl) 하위는 제외.
 
    표는 별도 블록으로 따로 처리하므로, 문단 텍스트를 모을 때는 표 내용을
    중복으로 끌어오지 않도록 tbl 하위를 건너뛴다.
    """
    parts = []
    tag = _local(elem.tag)
    if tag == "tbl":
        return ""
    if tag == "t" and elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_text_of(child))
    return "".join(parts)
 
 
def _table_block(tbl) -> dict:
    """tbl 요소를 {'type':'table','rows':[[셀,...], ...]} 로 변환."""
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
    """섹션 XML 을 문서 순서대로 훑어 문단/표 블록 리스트를 만든다."""
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
    """.hwpx(ZIP+XML)에서 문단/표 블록을 구조화해 추출. (blocks, 사용방식) 반환."""
    blocks = []
    with zipfile.ZipFile(hwpx_path) as zf:
        section_names = [
            n for n in zf.namelist() if re.match(r"Contents/section\d+\.xml$", n)
        ]
 
        if not section_names:
            raise RuntimeError("HWPX 안에서 Contents/section*.xml 을 찾지 못함(형식 확인 필요)")
 
        def section_index(name: str) -> int:
            m = re.search(r"section(\d+)\.xml$", name)
            return int(m.group(1)) if m else 0
 
        for name in sorted(section_names, key=section_index):
            try:
                root = ET.fromstring(zf.read(name))
            except ET.ParseError as exc:
                raise RuntimeError(f"{name} XML 파싱 실패: {exc}")
            _build_blocks(root, blocks)
 
    if not blocks:
        raise RuntimeError("추출된 문단/표가 없음(본문이 비어 있거나 형식 차이)")
 
    return blocks, "표준 zipfile+xml 직접 파싱"
 
 
# =====================================================================
# 3) 텍스트 정제 (.hwp 플레인 텍스트 결과 대상)
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
    """깨진 제어문자 제거 (탭/개행은 유지). NUL·폼피드 등 잡음 제거."""
    text = "".join(ch for ch in text if ch in ("\t", "\n") or ord(ch) >= 32 or ch == "\r")
    return text.replace("\r\n", "\n").replace("\r", "\n")
 
 
def _looks_like_heading(line: str) -> bool:
    """짧은 줄이면서 제목 패턴에 맞으면 True (본문 오인 방지용으로 길이 제한)."""
    s = line.strip()
    if not s or len(s) > 60:
        return False
    return any(p.match(s) for p in _HEADING_PATTERNS)
 
 
def clean_text_to_blocks(raw: str) -> list[dict]:
    """플레인 텍스트(.hwp 추출 결과)를 정제해 문단/제목 블록 리스트로 변환.
 
    - 제어문자 제거, 공백 정리, 과도한 빈 줄 축소
    - 줄 단위로 제목 후보를 식별해 heading 블록으로 분리
    - 나머지 연속 줄은 하나의 문단으로 묶음
    """
    text = _control_char_clean(raw)
    lines = [ln.rstrip() for ln in text.split("\n")]
 
    blocks = []
    buf = []
 
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
    """문단 블록 중 제목처럼 보이는 것을 heading 으로 승격(주로 .hwpx 경로)."""
    out = []
    for b in blocks:
        if b["type"] == "paragraph" and _looks_like_heading(b["text"]):
            out.append({"type": "heading", "text": b["text"].strip()})
            continue
        out.append(b)
    return out
 
 
# =====================================================================
# 4) 블록 -> Markdown / 구조화 레코드
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
# 5) 파일 단위 처리 (DRM 감지 + 연동 지점 + 추출 + 정제)
# =====================================================================
 
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"
 
 
def looks_drm_encrypted(path: Path) -> bool:
    """파일 시그니처가 정상 HWP/HWPX 가 아니면 DRM 암호화로 추정.
 
    DRM 보안문서는 디스크에서 암호화돼 있어 시그니처가 맞지 않는다.
    (손상 파일도 여기 걸릴 수 있으나, 안내 메시지로 구분 가능)
    """
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
    """확장자에 맞춰 추출+정제. (blocks, method, fmt) 반환."""
    if suffix == ".hwp":
        raw, method = extract_hwp(work_path)
        return clean_text_to_blocks(raw), method, "hwp"
    if suffix == ".hwpx":
        raw_blocks, method = extract_hwpx(work_path)
        return annotate_headings(raw_blocks), method, "hwpx"
    raise RuntimeError(f"지원하지 않는 형식: {suffix}")
 
 
def process_file(path: Path, mip=None) -> dict:
    """파일 1개를 추출+정제해서 record(dict) 반환. 실패 시 RuntimeError 전파.
 
    DRM 으로 감지되면, mip(복호화 클라이언트)가 있을 때만 사내 API 로 복호화한 뒤
    임시 평문 파일로 처리하고, 처리 후 임시 파일을 삭제한다.
 
    mip 은 `mip_decrypt.load_context(...)` 가 돌려주는 객체(사내 DRM 복호화
    구조, 이 파일에는 포함하지 않음)를 그대로 주입받는 자리다. 이 함수 자체는
    mip 객체가 `decrypt_file(path) -> bytes` 만 제공하면 그것으로 충분하다.
    """
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise RuntimeError(f"지원하지 않는 형식: {suffix}")
 
    work_path = path
    tmp_path = None
    decrypted = False
 
    if looks_drm_encrypted(path):
        if mip is None:
            raise RuntimeError(
                "DRM 보안문서로 보입니다. 복호화 설정이 필요합니다 "
                "(mip_config.local.json + 환경변수 MIP_SECRET_KEY)."
            )
 
        print("    · DRM 감지 → 사내 MIP API 로 복호화 요청")
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
            raise RuntimeError("정제 후 내용이 비어 있음")
 
        if decrypted:
            method = "DRM 복호화(MIP) 후 " + method
 
        return build_record(path, fmt, method, blocks)
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
 
 
# =====================================================================
# 6) CLI
# =====================================================================
 
def parse_cli(argv: list[str]) -> tuple[str | None, str | None]:
    """인자 파싱. 반환: (입력경로 or None, 출력폴더 or None)
 
    사용법:
        preprocess_hwp <입력폴더|파일>
        preprocess_hwp <입력폴더|파일> --out <출력폴더>
        preprocess_hwp --out <출력폴더> <입력폴더|파일>
    """
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
 
 
def collect_inputs(target_arg: str | None) -> tuple[list[Path], Path | None]:
    """입력 인자 해석. 폴더면 그 안의 hwp/hwpx 전부, 파일이면 그 파일.
    인자가 없으면 기본 입력 폴더(개발 모드에서만, rfp_hwp)를 대상으로 한다.
    반환: (대상파일목록, 기준폴더 or None)
    """
    if target_arg is not None:
        target = Path(target_arg)
    elif DEFAULT_INPUT_DIR is not None:
        target = DEFAULT_INPUT_DIR
    else:
        return [], None
 
    if target.is_dir():
        files = sorted(
            p for p in target.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
        )
        return files, target
    if target.is_file():
        return [target], target.parent
    return [], target
 
 
def main(argv: list[str]) -> int:
    target_arg, out_arg = parse_cli(argv)
    inputs, base = collect_inputs(target_arg)
 
    output_dir = Path(out_arg) if out_arg else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
 
    mip = mip_decrypt.load_context(BASE_DIR) if mip_decrypt is not None else None
 
    print("=" * 64)
    print("HWP/HWPX → AI용 자동 전처리")
    print(f"입력 위치 : {base if base is not None else '(미지정)'}")
    print(f"출력 폴더 : {output_dir}")
    print(f"DRM 복호화 : {'사용 가능 (사내 MIP)' if mip else '미설정 (DRM 문서는 건너뜀)'}")
    print("=" * 64)
 
    if base is None:
        print("\n처리할 폴더/파일을 인자로 지정하세요.")
        print('  예) preprocess_hwp.exe "C:\\대상\\폴더"')
        return 1
    if not inputs:
        print("\n처리할 .hwp / .hwpx 파일이 없습니다.")
        print(f"  → 확인할 위치: {base}")
        return 1
 
    summary = []
    failed = 0
    success = 0
 
    for path in inputs:
        print(f"\n[대상] {path.name}")
        try:
            record = process_file(path, mip)
        except RuntimeError as exc:
            print(f"    [X] 실패: {exc}")
            summary.append({"source_file": path.name, "status": "failed", "reason": str(exc)})
            failed += 1
            continue
        except Exception as exc:
            print(f"    [X] 실패(예외): {exc}")
            summary.append({"source_file": path.name, "status": "failed", "reason": repr(exc)})
            failed += 1
            continue
 
        stem = path.stem
        md_path = output_dir / (stem + ".md")
        json_path = output_dir / (stem + ".json")
 
        try:
            md_path.write_text(blocks_to_markdown(stem, record["blocks"]), encoding="utf-8")
            json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"    [X] 실패: 저장 오류: {exc}")
            summary.append(
                {"source_file": path.name, "status": "failed", "reason": f"저장 오류: {exc}"}
            )
            failed += 1
            continue
 
        c = record["block_counts"]
        print(f"    [OK] 성공: {record['extraction_method']}")
        print(
            f"      - 글자수 {record['char_count']:,} / 제목 {c['heading']}, "
            f"문단 {c['paragraph']}, 표 {c['table']}"
        )
        print(f"      - {md_path.name}, {json_path.name}")
 
        summary.append(
            {
                "source_file": path.name,
                "status": "success",
                "format": record["format"],
                "extraction_method": record["extraction_method"],
                "char_count": record["char_count"],
                "block_counts": c,
                "outputs": [md_path.name, json_path.name],
            }
        )
        success += 1
 
    (output_dir / "_summary.json").write_text(
        json.dumps(
            {
                "input": str(base) if base is not None else "",
                "total": len(inputs),
                "success": success,
                "failed": failed,
                "files": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
 
    print("\n================================================================")
    print("실행 결과 요약")
    print(f"  전체 파일 수 : {len(inputs)}")
    print(f"  성공 파일 수 : {success}")
    print(f"  실패 파일 수 : {failed}")
    print(f"  요약 파일    : {output_dir / '_summary.json'}")
    print("================================================================")
 
    return 0 if failed == 0 else 1
 
 
if __name__ == "__main__":
    sys.exit(main(sys.argv))
 